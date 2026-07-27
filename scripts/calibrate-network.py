#!/usr/bin/env python3
"""Independently check a netem profile before using it for pilot evidence."""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from typing import Any


def parse_ping(text: str) -> dict[str, float | None]:
    loss_match = re.search(r"(\d+(?:\.\d+)?)%\s*packet loss", text)
    rtt_match = re.search(
        r"(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/([\d.]+)/([\d.]+)\s*ms", text
    )
    if not loss_match:
        raise ValueError("Could not parse packet loss from ping output")
    return {
        "packet_loss_percent": float(loss_match.group(1)),
        "rtt_mean_ms": float(rtt_match.group(1)) if rtt_match else None,
        "rtt_mdev_ms": float(rtt_match.group(3)) if rtt_match else None,
    }


def run_ping(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    result: dict[str, Any] = {
        "command": command,
        "exit_code": completed.returncode,
        "raw_output": completed.stdout,
    }
    try:
        result.update(parse_ping(completed.stdout))
    except ValueError as error:
        result["parse_error"] = str(error)
    return result


def measure_namespace(namespace: str, host: str, count: int) -> dict[str, Any]:
    return run_ping(["sudo", "ip", "netns", "exec", namespace, "ping", "-n", "-c", str(count), host])


def measure_container(project: pathlib.Path, service: str, host: str, count: int) -> dict[str, Any]:
    return run_ping([
        "docker", "compose", "--project-directory", str(project), "exec", "-T", service,
        "ping", "-n", "-c", str(count), host,
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="pqcbench-client", help="Source namespace (the default backend)")
    parser.add_argument("--container", action="store_true", help="Measure from a Compose service instead")
    parser.add_argument("--project-directory", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parent.parent)
    parser.add_argument("--service", default="client", help="Compose source service when using --container")
    parser.add_argument("--host", default=None, help="Destination address or Compose service name")
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--expected-rtt-ms", type=float)
    parser.add_argument("--expected-loss-percent", type=float)
    parser.add_argument("--rtt-tolerance-ms", type=float, default=5.0)
    parser.add_argument("--loss-tolerance-percent", type=float, default=2.0)
    parser.add_argument("--output", type=pathlib.Path, help="Write calibration evidence as JSON as well as stdout")
    args = parser.parse_args()
    if args.count < 2:
        parser.error("--count must be at least 2")

    host = args.host or ("server" if args.container else "10.203.0.2")
    report = (
        measure_container(args.project_directory, args.service, host, args.count)
        if args.container
        else measure_namespace(args.namespace, host, args.count)
    )
    report["backend"] = "container" if args.container else "netns"
    report["source"] = args.service if args.container else args.namespace
    report["destination"] = host
    checks: dict[str, bool] = {"ping_completed": report["exit_code"] in (0, 1)}
    if args.expected_rtt_ms is not None and report.get("rtt_mean_ms") is not None:
        checks["rtt_within_tolerance"] = abs(float(report["rtt_mean_ms"]) - args.expected_rtt_ms) <= args.rtt_tolerance_ms
    if args.expected_loss_percent is not None and report.get("packet_loss_percent") is not None:
        checks["loss_within_tolerance"] = abs(float(report["packet_loss_percent"]) - args.expected_loss_percent) <= args.loss_tolerance_percent
    report["checks"] = checks
    report["ok"] = all(checks.values()) and "parse_error" not in report
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
