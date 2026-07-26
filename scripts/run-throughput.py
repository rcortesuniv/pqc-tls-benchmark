#!/usr/bin/env python3
"""Run a distinct, fixed-concurrency TLS throughput workload."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import pathlib
import subprocess
import sys
import time
from typing import Any


def load_config(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def worker(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return completed.returncode, completed.stdout, completed.stderr


def main() -> int:
    project = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, default=project / "config/experiment.json")
    parser.add_argument("--client", type=pathlib.Path, default=project / "build/tls_bench_client")
    parser.add_argument("--group", default="X25519MLKEM768")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--handshakes-per-worker", type=int, default=100)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    if args.workers < 1 or args.handshakes_per_worker < 1:
        parser.error("--workers and --handshakes-per-worker must be positive")

    config = load_config(args.config)
    if args.group not in config["groups"]:
        parser.error("--group must be configured")
    endpoint = config["endpoint"]
    backend = config["network_backend"]
    output = args.output or project / "results" / f"throughput-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    commands = []
    for worker_id in range(args.workers):
        commands.append([
            "sudo", "ip", "netns", "exec", backend["client_namespace"], str(args.client.resolve()),
            "--host", str(endpoint["host"]), "--port", str(endpoint["port"]),
            "--server-name", str(endpoint["server_name"]), "--ca-file", str((project / endpoint["ca_file"]).resolve()),
            "--group", args.group, "--batch-id", "throughput", "--cell-id", f"throughput-{args.group}",
            "--warmups", "0", "--attempts", str(args.handshakes_per_worker),
            "--timeout-ms", str(config["execution"]["timeout_ms"]),
        ])
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        completed = list(executor.map(worker, commands))
    elapsed = time.monotonic() - started
    observations = []
    errors = []
    for worker_id, (returncode, stdout, stderr) in enumerate(completed):
        if returncode:
            errors.append({"worker": worker_id, "exit_code": returncode, "stderr": stderr})
        for line in stdout.splitlines():
            observations.append(json.loads(line))
    successes = sum(row.get("status") == "success" for row in observations)
    report = {
        "schema_version": "1.0",
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "group": args.group,
        "fixed_concurrency": args.workers,
        "handshakes_per_worker": args.handshakes_per_worker,
        "requested_handshakes": args.workers * args.handshakes_per_worker,
        "observed_handshakes": len(observations),
        "successful_handshakes": successes,
        "elapsed_seconds": elapsed,
        "successful_handshakes_per_second": successes / elapsed if elapsed else None,
        "worker_errors": errors,
    }
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
