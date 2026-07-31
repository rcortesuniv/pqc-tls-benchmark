#!/usr/bin/env python3
"""Measure the measurement-noise floor against the same statistical pipeline
used for real group-vs-group comparisons.

Runs repeated handshakes of a single group, splits each batch's recorded
attempts into two interleaved arms (even/odd sequence position), and treats
the arm-vs-arm median delta exactly like a real batch-level contrast: the
same bootstrap CI, sign-permutation test and TOST equivalence test from
analysis/summarise.py. Since both arms negotiate the identical group, any
non-zero effect this reports is pure measurement noise (scheduler jitter,
timing resolution, transient host load) rather than a cryptographic or
protocol difference -- letting a real finding (e.g. the primary contrast) be
judged against what noise alone would produce under this exact methodology.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "analysis"))
from summarise import bootstrap_mean_interval, sign_permutation_pvalue, tost_equivalence  # noqa: E402


def load_config(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cpu_pinning_plan() -> dict[str, Any]:
    """Mirrors run-experiment.py's client-side pinning decision, so the noise
    floor is measured under the same conditions real batches run under."""
    if os.environ.get("PQC_CPU_PINNING", "1") == "0":
        return {"enabled": False, "reason": "disabled via PQC_CPU_PINNING=0"}
    if shutil.which("taskset") is None:
        return {"enabled": False, "reason": "taskset not found"}
    if (os.cpu_count() or 1) < 2:
        return {"enabled": False, "reason": "fewer than 2 CPUs available"}
    return {"enabled": True, "client_cpu": int(os.environ.get("PQC_CLIENT_CPU", "1"))}


def run_arm_pair(
    client: pathlib.Path, endpoint: dict[str, Any], ca_file: pathlib.Path, group: str,
    namespace: str, cpu_pinning: dict[str, Any], attempts_per_arm: int, timeout_ms: int,
) -> tuple[list[float], list[float]]:
    """One continuous run of 2*attempts_per_arm handshakes, split by sequence
    parity into two interleaved arms."""
    command = ["sudo", "ip", "netns", "exec", namespace]
    if cpu_pinning["enabled"]:
        command += ["taskset", "-c", str(cpu_pinning["client_cpu"])]
    command += [
        str(client.resolve()), "--host", str(endpoint["host"]), "--port", str(endpoint["port"]),
        "--server-name", str(endpoint["server_name"]), "--ca-file", str(ca_file.resolve()),
        "--group", group, "--batch-id", "noise-floor", "--cell-id", f"noise-floor-{group}",
        "--warmups", "0", "--attempts", str(attempts_per_arm * 2), "--timeout-ms", str(timeout_ms),
    ]
    completed = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    latencies: list[float] = []
    for line in completed.stdout.splitlines():
        row = json.loads(line)
        if row.get("status") == "success":
            latencies.append(float(row["handshake_latency_ms"]))
    if len(latencies) < attempts_per_arm * 2:
        raise RuntimeError(
            f"Only {len(latencies)}/{attempts_per_arm * 2} handshakes succeeded; "
            "inspect the lab before trusting this noise-floor estimate."
        )
    arm_a = latencies[0::2]
    arm_b = latencies[1::2]
    return arm_a, arm_b


def main() -> int:
    project = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, default=project / "config/experiment.json")
    parser.add_argument("--client", type=pathlib.Path, default=project / "build/tls_bench_client")
    parser.add_argument(
        "--group", default=None,
        help="Group to measure (default: analysis.primary_comparison.comparison_group if configured, else X25519MLKEM768)",
    )
    parser.add_argument("--batches", type=int, default=10, help="Match the real experiment's batch count for a fair comparison")
    parser.add_argument("--attempts-per-arm", type=int, default=100, help="Matches execution.recorded_handshakes_per_cell by default")
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.batches < 2:
        parser.error("--batches must be at least 2 (paired tests need >=2 batches)")
    if args.attempts_per_arm < 1:
        parser.error("--attempts-per-arm must be positive")

    config = load_config(args.config)
    primary = config.get("analysis", {}).get("primary_comparison") or {}
    group = args.group or primary.get("comparison_group") or "X25519MLKEM768"
    endpoint = config["endpoint"]
    backend = config["network_backend"]
    if backend.get("type") != "netns":
        parser.error("calibrate-noise-floor.py only supports the netns backend")
    ca_file = project / endpoint["ca_file"]
    timeout_ms = int(config.get("execution", {}).get("timeout_ms", 10000))
    cpu_pinning = cpu_pinning_plan()

    deltas: list[float] = []
    per_batch: list[dict[str, Any]] = []
    for batch in range(1, args.batches + 1):
        arm_a, arm_b = run_arm_pair(
            args.client, endpoint, ca_file, group, backend["client_namespace"],
            cpu_pinning, args.attempts_per_arm, timeout_ms,
        )
        median_a = sorted(arm_a)[len(arm_a) // 2]
        median_b = sorted(arm_b)[len(arm_b) // 2]
        delta = median_b - median_a
        deltas.append(delta)
        per_batch.append({
            "batch": batch, "n_per_arm": len(arm_a),
            "median_arm_a_ms": median_a, "median_arm_b_ms": median_b, "delta_ms": delta,
        })
        print(f"[{batch:02d}/{args.batches:02d}] {group}: arm A median {median_a:.4f} ms, arm B median {median_b:.4f} ms, delta {delta:+.4f} ms", flush=True)

    settings = config.get("analysis", {})
    resamples = int(settings.get("bootstrap_resamples", 5000))
    seed = int(settings.get("seed", 0))
    stats = bootstrap_mean_interval(deltas, resamples=resamples, seed=seed)
    stats["permutation_pvalue"] = sign_permutation_pvalue(deltas)
    margins = sorted({float(value) for value in settings.get("acceptance_thresholds_ms", []) if float(value) > 0})
    stats["equivalence_tests"] = [tost_equivalence(deltas, margin) for margin in margins]

    report = {
        "schema_version": "1.0",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "purpose": (
            "Both arms negotiate the same group; any non-zero effect reported here is "
            "measurement noise, not a real cryptographic or protocol difference. Compare "
            "against a real contrast's mean and CI to judge whether it exceeds the noise floor."
        ),
        "group": group,
        "batches": args.batches,
        "attempts_per_arm": args.attempts_per_arm,
        "cpu_pinning": cpu_pinning,
        "per_batch": per_batch,
        "noise_floor_ms": stats,
    }
    output = args.output or project / "results" / f"noise-floor-{group}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
