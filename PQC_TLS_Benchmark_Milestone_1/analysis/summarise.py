#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import pathlib
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


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


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
    write_csv(analysis_dir / "batch_cell_summary.csv", summaries)
    write_csv(analysis_dir / "primary_batch_deltas.csv", deltas)

    report = {
        "observations": len(observations),
        "batch_cells": len(summaries),
        "primary_batch_deltas": len(deltas),
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
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

