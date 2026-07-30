#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import itertools
import json
import math
import pathlib
import random
import statistics
import sys
from collections import defaultdict
from typing import Any, Iterable


REQUIRED_FIELDS = {
    "schema_version",
    "batch_id",
    "cell_id",
    "sequence",
    "requested_group",
    "status",
    "handshake_latency_ms",
    "tls_bytes_read",
    "tls_bytes_written",
}


def percentile(values: list[float], proportion: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def load_observations(raw_dir: pathlib.Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
                missing = REQUIRED_FIELDS - row.keys()
                if missing:
                    raise ValueError(
                        f"{path}:{line_number}: missing fields: {', '.join(sorted(missing))}"
                    )
                row["_source_file"] = path.name
                observations.append(row)
    if not observations:
        raise ValueError(f"No JSONL observations found in {raw_dir}")
    return observations


def parse_cell(cell_id: str) -> tuple[int, float]:
    parts = cell_id.split("__")
    rtt = int(parts[1].removeprefix("rtt-").removesuffix("ms"))
    loss = float(parts[2].removeprefix("loss-").removesuffix("pct").replace("p", "."))
    return rtt, loss


def grouped_summary(observations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in observations:
        grouped[(row["batch_id"], row["cell_id"])].append(row)

    summaries: list[dict[str, Any]] = []
    for (batch_id, cell_id), rows in sorted(grouped.items()):
        group = rows[0]["requested_group"]
        rtt_ms, loss_percent = parse_cell(cell_id)
        successful = [row for row in rows if row["status"] == "success"]
        latencies = [float(row["handshake_latency_ms"]) for row in successful]
        bytes_read = [int(row["tls_bytes_read"]) for row in successful]
        bytes_written = [int(row["tls_bytes_written"]) for row in successful]
        summaries.append(
            {
                "batch_id": batch_id,
                "cell_id": cell_id,
                "group": group,
                "rtt_ms": rtt_ms,
                "loss_percent_each_direction": loss_percent,
                "attempts": len(rows),
                "successes": len(successful),
                "failures": len(rows) - len(successful),
                "failure_rate": (len(rows) - len(successful)) / len(rows),
                "median_latency_ms": statistics.median(latencies) if latencies else math.nan,
                "mean_latency_ms": statistics.fmean(latencies) if latencies else math.nan,
                "sd_latency_ms": statistics.stdev(latencies) if len(latencies) > 1 else math.nan,
                "q1_latency_ms": percentile(latencies, 0.25),
                "q3_latency_ms": percentile(latencies, 0.75),
                "p95_latency_ms": percentile(latencies, 0.95),
                "p99_latency_ms": percentile(latencies, 0.99),
                "median_tls_bytes_read": statistics.median(bytes_read) if bytes_read else math.nan,
                "median_tls_bytes_written": statistics.median(bytes_written) if bytes_written else math.nan,
            }
        )
    return summaries


def primary_deltas(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (
            row["batch_id"],
            row["rtt_ms"],
            row["loss_percent_each_direction"],
            row["group"],
        ): row
        for row in summaries
    }
    deltas: list[dict[str, Any]] = []
    condition_batches = {
        (row["batch_id"], row["rtt_ms"], row["loss_percent_each_direction"])
        for row in summaries
    }
    for batch_id, rtt_ms, loss in sorted(condition_batches):
        classical = indexed.get((batch_id, rtt_ms, loss, "X25519"))
        hybrid = indexed.get((batch_id, rtt_ms, loss, "X25519MLKEM768"))
        if not classical or not hybrid:
            continue
        absolute = hybrid["median_latency_ms"] - classical["median_latency_ms"]
        percent = (
            absolute / classical["median_latency_ms"] * 100.0
            if classical["median_latency_ms"] > 0
            else math.nan
        )
        deltas.append(
            {
                "batch_id": batch_id,
                "rtt_ms": rtt_ms,
                "loss_percent_each_direction": loss,
                "x25519_median_ms": classical["median_latency_ms"],
                "hybrid_median_ms": hybrid["median_latency_ms"],
                "hybrid_minus_x25519_ms": absolute,
                "hybrid_overhead_percent": percent,
                "failure_rate_delta": hybrid["failure_rate"] - classical["failure_rate"],
            }
        )
    return deltas


def pairwise_deltas(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {
        (row["batch_id"], row["rtt_ms"], row["loss_percent_each_direction"], row["group"]): row
        for row in summaries
    }
    conditions = sorted({key[:3] for key in indexed})
    groups = sorted({row["group"] for row in summaries})
    rows: list[dict[str, Any]] = []
    for batch_id, rtt_ms, loss in conditions:
        for baseline, comparison in itertools.combinations(groups, 2):
            left = indexed.get((batch_id, rtt_ms, loss, baseline))
            right = indexed.get((batch_id, rtt_ms, loss, comparison))
            if not left or not right or not math.isfinite(left["median_latency_ms"]) or not math.isfinite(right["median_latency_ms"]):
                continue
            rows.append({
                "batch_id": batch_id,
                "rtt_ms": rtt_ms,
                "loss_percent_each_direction": loss,
                "baseline_group": baseline,
                "comparison_group": comparison,
                "comparison_minus_baseline_ms": right["median_latency_ms"] - left["median_latency_ms"],
                "failure_rate_delta": right["failure_rate"] - left["failure_rate"],
            })
    return rows


def bootstrap_mean_interval(values: list[float], *, resamples: int, seed: int) -> dict[str, float | int | None]:
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return {"n": 0, "mean": None, "ci95_low": None, "ci95_high": None}
    generator = random.Random(seed)
    means = sorted(statistics.fmean(generator.choice(finite) for _ in finite) for _ in range(resamples))
    return {
        "n": len(finite), "mean": statistics.fmean(finite),
        "ci95_low": percentile(means, 0.025), "ci95_high": percentile(means, 0.975),
    }


def lag1_autocorrelation(values: list[float]) -> float | None:
    finite = [value for value in values if math.isfinite(value)]
    if len(finite) < 3:
        return None
    mean = statistics.fmean(finite)
    denominator = sum((value - mean) ** 2 for value in finite)
    if denominator == 0:
        return None
    return sum((finite[index] - mean) * (finite[index - 1] - mean) for index in range(1, len(finite))) / denominator


def sign_permutation_pvalue(values: list[float]) -> float | None:
    """Two-sided, paired randomisation test for a batch-level mean contrast."""
    finite = [value for value in values if math.isfinite(value)]
    if not finite:
        return None
    observed = abs(statistics.fmean(finite))
    if len(finite) > 16:
        generator = random.Random(0)
        signed_means = [abs(statistics.fmean(value if generator.getrandbits(1) else -value for value in finite)) for _ in range(20000)]
    else:
        signed_means = [abs(statistics.fmean(sign * value for sign, value in zip(signs, finite))) for signs in itertools.product((-1, 1), repeat=len(finite))]
    return sum(value >= observed - 1e-12 for value in signed_means) / len(signed_means)


def holm_adjust(pvalues: list[float | None]) -> list[float | None]:
    adjusted: list[float | None] = [None] * len(pvalues)
    ordered = sorted((value, index) for index, value in enumerate(pvalues) if value is not None)
    running = 0.0
    total = len(ordered)
    for rank, (value, index) in enumerate(ordered):
        running = max(running, min(1.0, value * (total - rank)))
        adjusted[index] = running
    return adjusted


def validate_dataset(result_dir: pathlib.Path, observations: list[dict[str, Any]]) -> list[str]:
    issues: list[str] = []
    sequences: set[tuple[str, str, int]] = set()
    for row in observations:
        identity = (str(row["batch_id"]), str(row["cell_id"]), int(row["sequence"]))
        if identity in sequences:
            issues.append(f"duplicate sequence: {identity}")
        sequences.add(identity)
        latency = row["handshake_latency_ms"]
        if row["status"] == "success" and (not isinstance(latency, (int, float)) or not math.isfinite(float(latency)) or latency < 0):
            issues.append(f"invalid successful latency: {identity}")
        if any(not isinstance(row[field], int) or row[field] < 0 for field in ("tls_bytes_read", "tls_bytes_written")):
            issues.append(f"invalid TLS byte count: {identity}")
    successful = [row for row in observations if row["status"] == "success"]
    if successful and all(row["tls_bytes_written"] == 0 for row in successful):
        issues.append("no outbound TLS bytes were recorded for successful handshakes")
    integrity_path = result_dir / "integrity.json"
    if integrity_path.exists():
        expected = json.loads(integrity_path.read_text(encoding="utf-8"))
        for relative, digest in expected.items():
            path = result_dir / relative
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
            if actual != digest:
                issues.append(f"integrity mismatch: {relative}")
    schedule_path = result_dir / "schedule.json"
    config_path = result_dir / "config.snapshot.json"
    if schedule_path.exists() and config_path.exists():
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        config = json.loads(config_path.read_text(encoding="utf-8"))
        expected_attempts = config["execution"]["recorded_handshakes_per_cell"]
        completed = [entry for entry in schedule if entry.get("state") == "completed"]
        actual_counts: dict[tuple[str, str], int] = defaultdict(int)
        for row in observations:
            actual_counts[(row["batch_id"], row["cell_id"])] += 1
        for entry in completed:
            key = (entry["batch_id"], entry["cell_id"])
            if actual_counts[key] != expected_attempts:
                issues.append(f"incomplete cell {key}: expected {expected_attempts}, found {actual_counts[key]}")
        unfinished = [entry["cell_id"] for entry in schedule if entry.get("state") != "completed"]
        if unfinished:
            issues.append(f"unfinished scheduled cells: {len(unfinished)}")
    return issues


def confirmatory_analysis(pairwise: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    settings = config.get("analysis", {})
    resamples = int(settings.get("bootstrap_resamples", 5000))
    seed = int(settings.get("seed", 0))
    thresholds = [float(value) for value in settings.get("acceptance_thresholds_ms", [])]
    grouped: dict[tuple[Any, ...], list[float]] = defaultdict(list)
    for row in pairwise:
        key = (row["rtt_ms"], row["loss_percent_each_direction"], row["baseline_group"], row["comparison_group"])
        grouped[key].append(float(row["comparison_minus_baseline_ms"]))
    result: list[dict[str, Any]] = []
    raw_pvalues: list[float | None] = []
    for index, (key, values) in enumerate(sorted(grouped.items())):
        report = dict(zip(("rtt_ms", "loss_percent_each_direction", "baseline_group", "comparison_group"), key))
        report.update(bootstrap_mean_interval(values, resamples=resamples, seed=seed + index))
        report["lag1_autocorrelation"] = lag1_autocorrelation(values)
        report["permutation_pvalue"] = sign_permutation_pvalue(values)
        report["acceptance_threshold_sensitivity"] = [
            {
                "threshold_ms": threshold,
                "batches_at_or_below_threshold": sum(value <= threshold for value in values),
                "proportion_at_or_below_threshold": sum(value <= threshold for value in values) / len(values),
            }
            for threshold in thresholds
        ]
        raw_pvalues.append(report["permutation_pvalue"])
        result.append(report)
    for report, adjusted in zip(result, holm_adjust(raw_pvalues)):
        report["holm_adjusted_pvalue"] = adjusted
    return result


def primary_contrast_analysis(pairwise: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any] | None:
    """Analyse one pre-specified comparison without applying exploratory multiplicity control."""
    primary = config.get("analysis", {}).get("primary_comparison")
    if not isinstance(primary, dict):
        return None
    required = ("baseline_group", "comparison_group", "rtt_ms", "loss_percent_each_direction")
    if any(key not in primary for key in required):
        return None
    values = [
        float(row["comparison_minus_baseline_ms"])
        for row in pairwise
        if row["baseline_group"] == primary["baseline_group"]
        and row["comparison_group"] == primary["comparison_group"]
        and float(row["rtt_ms"]) == float(primary["rtt_ms"])
        and float(row["loss_percent_each_direction"]) == float(primary["loss_percent_each_direction"])
    ]
    settings = config.get("analysis", {})
    report = dict(primary)
    report.update(
        bootstrap_mean_interval(
            values,
            resamples=int(settings.get("bootstrap_resamples", 5000)),
            seed=int(settings.get("seed", 0)),
        )
    )
    report["permutation_pvalue"] = sign_permutation_pvalue(values)
    report["lag1_autocorrelation"] = lag1_autocorrelation(values)
    report["multiplicity_adjustment"] = "none: one pre-specified primary comparison"
    return report


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def pooled_tail_summary(observations: list[dict[str, Any]], config: dict[str, Any], resamples: int = 5000) -> list[dict[str, Any]]:
    """Pooled per-condition tail quantiles with block, plain and two-stage bootstrap CIs.

    Three p99 interval schemes are reported so the choice of tail estimator is
    evidence-based rather than presumptive:

      * block (cluster) bootstrap - resamples whole batches, preserving the
        within-batch netem loss realisation; the primary tail estimator.
      * plain pooled bootstrap - resamples individual handshakes, ignoring the
        batch clustering; a naive comparator.
      * two-stage bootstrap - resamples batches, then handshakes within each
        resampled batch; a conservative sensitivity that additionally captures
        any within-batch loss correlation.

    Handshakes within a batch share a netem loss realisation, so the block
    bootstrap is the primary estimator; the plain and two-stage schemes are
    reported as comparators/sensitivity.
    """
    settings = config.get("analysis", {})
    seed = int(settings.get("seed", 0))
    resamples = int(settings.get("pooled_tail_bootstrap_resamples", resamples))
    rng = random.Random(seed)
    grouped: dict[tuple[str, int, float], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in observations:
        if row["status"] != "success":
            continue
        rtt_ms, loss_percent = parse_cell(row["cell_id"])
        grouped[(row["requested_group"], rtt_ms, loss_percent)][row["batch_id"]].append(float(row["handshake_latency_ms"]))

    def block_ci(batch_latencies: list[list[float]], proportion: float) -> tuple[float, float]:
        n_batches = len(batch_latencies)
        if n_batches < 2:
            return (math.nan, math.nan)
        draws: list[float] = []
        for _ in range(resamples):
            pool = [value for i in (rng.randrange(n_batches) for _ in range(n_batches)) for value in batch_latencies[i]]
            draws.append(percentile(pool, proportion))
        draws.sort()
        return (percentile(draws, 0.025), percentile(draws, 0.975))

    def plain_ci(pooled: list[float], proportion: float) -> tuple[float, float]:
        if len(pooled) < 2:
            return (math.nan, math.nan)
        draws = [percentile(rng.choices(pooled, k=len(pooled)), proportion) for _ in range(resamples)]
        draws.sort()
        return (percentile(draws, 0.025), percentile(draws, 0.975))

    def two_stage_ci(batch_latencies: list[list[float]], proportion: float) -> tuple[float, float]:
        n_batches = len(batch_latencies)
        if n_batches < 2:
            return (math.nan, math.nan)
        draws: list[float] = []
        for _ in range(resamples):
            pool: list[float] = []
            for i in (rng.randrange(n_batches) for _ in range(n_batches)):
                src = batch_latencies[i]
                pool.extend(rng.choices(src, k=len(src)))
            draws.append(percentile(pool, proportion))
        draws.sort()
        return (percentile(draws, 0.025), percentile(draws, 0.975))

    out: list[dict[str, Any]] = []
    for (group, rtt_ms, loss_percent), batches in sorted(grouped.items()):
        batch_latencies = list(batches.values())
        pooled = [value for latencies in batch_latencies for value in latencies]
        if not pooled:
            continue
        # Block is computed first so its rng draw sequence is unchanged, keeping
        # the primary estimator reproducible; plain and two-stage draw afterwards.
        ci99 = block_ci(batch_latencies, 0.99)
        plain99 = plain_ci(pooled, 0.99)
        twostage99 = two_stage_ci(batch_latencies, 0.99)
        out.append({
            "group": group,
            "rtt_ms": rtt_ms,
            "loss_percent_each_direction": loss_percent,
            "n_handshakes": len(pooled),
            "n_batches": len(batch_latencies),
            "pooled_p95_ms": percentile(pooled, 0.95),
            "pooled_p99_ms": percentile(pooled, 0.99),
            "p99_block_ci95_low_ms": ci99[0],
            "p99_block_ci95_high_ms": ci99[1],
            "p99_plain_ci95_low_ms": plain99[0],
            "p99_plain_ci95_high_ms": plain99[1],
            "p99_twostage_ci95_low_ms": twostage99[0],
            "p99_twostage_ci95_high_ms": twostage99[1],
        })
    return out


def compute_findings(
    report: dict[str, Any],
    deltas: list[dict[str, Any]],
    confirmatory: list[dict[str, Any]],
    primary_contrast: dict[str, Any] | None,
    pooled_tail: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Auto-generated, per-run prose summary. Every claim is derived from this
    run's own already-computed outputs; nothing here re-analyses raw data."""
    observations = report["observations"]
    successes = report["status_counts"].get("success", 0)
    validation_summary = (
        f"{successes:,}/{observations:,} handshakes succeeded ({successes / observations:.1%})."
        if observations
        else "No observations were recorded."
    )
    validation_summary += (
        f" Validation flagged {len(report['issues'])} issue(s)." if report["issues"] else " Validation passed with no issues."
    )

    if primary_contrast and primary_contrast.get("mean") is not None:
        pc = primary_contrast
        excludes_zero = pc["ci95_low"] is not None and (pc["ci95_low"] > 0 or pc["ci95_high"] < 0)
        verdict = "significant" if excludes_zero else "not significant"
        primary_finding = {
            "available": True,
            "verdict": verdict,
            "summary": (
                f"{pc['comparison_group']} costs a mean {pc['mean']:+.3f} ms vs {pc['baseline_group']} at "
                f"{pc['rtt_ms']:g} ms RTT / {pc['loss_percent_each_direction']:g}% loss (95% CI "
                f"{pc['ci95_low']:.3f} to {pc['ci95_high']:.3f} ms, permutation p="
                f"{pc['permutation_pvalue']:.4f}; one pre-specified comparison, no multiplicity adjustment). "
                f"Result: {verdict} at the 95% level."
            ),
        }
    else:
        primary_finding = {
            "available": False,
            "summary": (
                "No pre-specified primary comparison is configured (analysis.primary_comparison is missing from "
                "the experiment config), so no primary-contrast verdict was computed for this run. The exploratory "
                "contrasts below are Holm-adjusted and are not a substitute for a pre-registered primary hypothesis test."
            ),
        }

    n_contrasts = len(confirmatory)
    n_significant = sum(
        1 for row in confirmatory
        if row.get("holm_adjusted_pvalue") is not None and row["holm_adjusted_pvalue"] < 0.05
    )
    batches = config.get("execution", {}).get("batches")
    multiplicity_summary = f"{n_significant} of {n_contrasts} exploratory contrasts remain significant after Holm adjustment (p < 0.05)."
    if isinstance(batches, int) and batches > 0 and n_contrasts:
        if batches <= 16:
            min_pvalue = 2.0 ** (1 - batches)
            floor_note = f"the exact paired sign-permutation test has a p-value floor of 2/2^{batches} ≈ {min_pvalue:.5f}"
        else:
            min_pvalue = 1.0 / 20000
            floor_note = "the Monte Carlo permutation test (20,000 draws) has a p-value floor around 0.00005"
        multiplicity_summary += f" With {batches} batches, {floor_note}."
        bonferroni_threshold = 0.05 / n_contrasts
        if min_pvalue > bonferroni_threshold:
            multiplicity_summary += (
                f" That floor exceeds the ~{bonferroni_threshold:.5f} raw p-value roughly needed to survive "
                f"correction across {n_contrasts} comparisons, so real, consistent effects can still fail Holm "
                f"adjustment purely from limited batch count — more batches, not more evidence, would be needed."
            )
    multiplicity_finding = {
        "summary": multiplicity_summary,
        "n_contrasts": n_contrasts,
        "n_holm_significant": n_significant,
    }

    delta_values = [
        float(row["hybrid_minus_x25519_ms"]) for row in deltas
        if math.isfinite(float(row.get("hybrid_minus_x25519_ms", math.nan)))
    ]
    if delta_values:
        hybrid_finding = {
            "available": True,
            "summary": (
                f"Across {len(delta_values)} batch-conditions, X25519MLKEM768 costs "
                f"{min(delta_values):+.3f} to {max(delta_values):+.3f} ms more than X25519 per handshake "
                f"(median {statistics.median(delta_values):+.3f} ms)."
            ),
        }
    else:
        hybrid_finding = {
            "available": False,
            "summary": "No paired X25519 / X25519MLKEM768 batch data is available for this run.",
        }

    tail_finding = {"available": False, "summary": "No pooled tail data is available for this run."}
    if pooled_tail:
        max_loss = max(row["loss_percent_each_direction"] for row in pooled_tail)
        worst_rtt = max(
            (row["rtt_ms"] for row in pooled_tail if row["loss_percent_each_direction"] == max_loss),
            default=None,
        )
        worst = [
            row for row in pooled_tail
            if row["loss_percent_each_direction"] == max_loss and row["rtt_ms"] == worst_rtt
        ]
        baseline = [
            row for row in pooled_tail
            if row["loss_percent_each_direction"] == 0.0 and row["rtt_ms"] == worst_rtt
        ]
        if worst and baseline:
            p99_worst = statistics.median(row["pooled_p99_ms"] for row in worst)
            p99_baseline = statistics.median(row["pooled_p99_ms"] for row in baseline)
            overlapping = all(
                a["p99_block_ci95_low_ms"] <= b["p99_block_ci95_high_ms"]
                and b["p99_block_ci95_low_ms"] <= a["p99_block_ci95_high_ms"]
                for a in worst for b in worst
            )
            group_note = (
                "with overlapping 95% CIs across all groups (no evidence of a group-specific effect)"
                if overlapping
                else "with non-overlapping CIs between at least two groups (possible group-specific tail effect — inspect the pooled tail table)"
            )
            ratio = p99_worst / p99_baseline if p99_baseline else math.nan
            tail_finding = {
                "available": True,
                "summary": (
                    f"At {worst_rtt:g} ms RTT / {max_loss:g}% loss (the harshest tested condition), pooled p99 "
                    f"latency reaches {p99_worst:.0f} ms, {ratio:.1f}x the 0%-loss p99 at the same RTT "
                    f"({p99_baseline:.0f} ms), {group_note}."
                ),
            }

    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "validation": {"summary": validation_summary},
        "primary_contrast": primary_finding,
        "multiplicity": multiplicity_finding,
        "hybrid_overhead": hybrid_finding,
        "tail_under_loss": tail_finding,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("result_dir", type=pathlib.Path)
    args = parser.parse_args()
    raw_dir = args.result_dir / "raw"
    analysis_dir = args.result_dir / "analysis"
    analysis_dir.mkdir(exist_ok=True)

    observations = load_observations(raw_dir)
    summaries = grouped_summary(observations)
    deltas = primary_deltas(summaries)
    all_pairwise = pairwise_deltas(summaries)
    config_path = args.result_dir / "config.snapshot.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    validation_issues = validate_dataset(args.result_dir, observations)
    confirmatory = confirmatory_analysis(all_pairwise, config)
    primary_contrast = primary_contrast_analysis(all_pairwise, config)
    write_csv(analysis_dir / "batch_cell_summary.csv", summaries)
    write_csv(analysis_dir / "primary_batch_deltas.csv", deltas)
    write_csv(analysis_dir / "pairwise_batch_deltas.csv", all_pairwise)
    pooled_tail = pooled_tail_summary(observations, config)
    write_csv(analysis_dir / "pooled_tail_summary.csv", pooled_tail)

    report = {
        "observations": len(observations),
        "batch_cells": len(summaries),
        "primary_batch_deltas": len(deltas),
        "valid": not validation_issues,
        "issues": validation_issues,
        "status_counts": dict(
            sorted(
                {
                    status: sum(1 for row in observations if row["status"] == status)
                    for status in {row["status"] for row in observations}
                }.items()
            )
        ),
    }
    (analysis_dir / "validation.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (analysis_dir / "confirmatory_analysis.json").write_text(
        json.dumps(
            {
                "method": "batch-level percentile bootstrap intervals; paired sign randomisation tests with Holm adjustment",
                "bootstrap_resamples": config.get("analysis", {}).get("bootstrap_resamples", 5000),
                "primary_contrast": primary_contrast,
                "contrasts": confirmatory,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    findings = compute_findings(report, deltas, confirmatory, primary_contrast, pooled_tail, config)
    (analysis_dir / "findings.json").write_text(
        json.dumps(findings, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0 if not validation_issues else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
