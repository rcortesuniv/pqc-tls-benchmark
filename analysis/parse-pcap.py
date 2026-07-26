#!/usr/bin/env python3
"""Summarise TCP payload bytes from a pcap using tshark's decoded fields."""
from __future__ import annotations

import argparse
import csv
import pathlib
import subprocess
import sys
from collections import defaultdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()
    command = ["tshark", "-r", str(args.pcap), "-Y", "tcp", "-T", "fields", "-E", "separator=,",
               "-e", "ip.src", "-e", "ip.dst", "-e", "tcp.len"]
    completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        print(completed.stderr, file=sys.stderr)
        return completed.returncode
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for line in completed.stdout.splitlines():
        source, destination, payload = (line.split(",") + ["", "", ""])[:3]
        if source and destination and payload.isdigit():
            totals[(source, destination)] += int(payload)
    rows = [{"source": source, "destination": destination, "tcp_payload_bytes": total}
            for (source, destination), total in sorted(totals.items())]
    if args.output:
        with args.output.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=["source", "destination", "tcp_payload_bytes"])
            writer.writeheader()
            writer.writerows(rows)
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=["source", "destination", "tcp_payload_bytes"])
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
