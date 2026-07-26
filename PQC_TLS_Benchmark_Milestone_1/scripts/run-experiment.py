#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import itertools
import json
import os
import pathlib
import platform
import random
import shlex
import subprocess
import sys
import time
from typing import Any


@dataclasses.dataclass(frozen=True)
class Cell:
    group: str
    rtt_ms: int
    loss_percent: float

    @property
    def identifier(self) -> str:
        loss = str(self.loss_percent).replace(".", "p")
        return f"{self.group}__rtt-{self.rtt_ms}ms__loss-{loss}pct"


def load_config(path: pathlib.Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    required = ("schema_version", "experiment_id", "seed", "groups", "network", "execution", "endpoint")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError(f"Missing configuration keys: {', '.join(missing)}")
    if len(set(config["groups"])) != len(config["groups"]):
        raise ValueError("TLS group names must be unique")
    if config["execution"]["batches"] < 1:
        raise ValueError("execution.batches must be at least 1")
    return config


def cells_from_config(config: dict[str, Any]) -> list[Cell]:
    return [
        Cell(group, int(rtt), float(loss))
        for group, rtt, loss in itertools.product(
            config["groups"],
            config["network"]["rtt_ms"],
            config["network"]["loss_percent_each_direction"],
        )
    ]


def schedule(config: dict[str, Any]) -> list[tuple[int, Cell]]:
    cells = cells_from_config(config)
    rng = random.Random(config["seed"])
    planned: list[tuple[int, Cell]] = []
    for batch in range(1, config["execution"]["batches"] + 1):
        order = cells.copy()
        rng.shuffle(order)
        planned.extend((batch, cell) for cell in order)
    return planned


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def apply_netem(config: dict[str, Any], cell: Cell, dry_run: bool) -> list[list[str]]:
    backend = config["network_backend"]
    one_way_delay = cell.rtt_ms / 2.0
    commands: list[list[str]] = []
    for namespace, interface in (
        (backend["client_namespace"], backend["client_interface"]),
        (backend["server_namespace"], backend["server_interface"]),
    ):
        netem = [
            "sudo", "ip", "netns", "exec", namespace,
            "tc", "qdisc", "replace", "dev", interface, "root", "netem",
        ]
        if one_way_delay:
            netem.extend(["delay", f"{one_way_delay:g}ms"])
        if cell.loss_percent:
            netem.extend(["loss", f"{cell.loss_percent:g}%"])
        if not one_way_delay and not cell.loss_percent:
            netem.extend(["delay", "0ms"])
        commands.append(netem)
        if not dry_run:
            run(netem)
    return commands


def verify_netem(config: dict[str, Any], dry_run: bool) -> dict[str, str]:
    backend = config["network_backend"]
    evidence: dict[str, str] = {}
    for namespace, interface in (
        (backend["client_namespace"], backend["client_interface"]),
        (backend["server_namespace"], backend["server_interface"]),
    ):
        command = [
            "sudo", "ip", "netns", "exec", namespace,
            "tc", "qdisc", "show", "dev", interface,
        ]
        evidence[namespace] = shlex.join(command) if dry_run else run(command, capture=True).stdout.strip()
    return evidence


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment_manifest(
    config: dict[str, Any], config_path: pathlib.Path, client: pathlib.Path
) -> dict[str, Any]:
    openssl_text: str | None = None
    openssl_bin = config.get("software", {}).get("openssl_bin")
    if openssl_bin:
        try:
            openssl_text = run([str(openssl_bin), "version", "-a"], capture=True).stdout
        except (OSError, subprocess.CalledProcessError):
            openssl_text = None
    return {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "config_sha256": sha256(config_path),
        "client_sha256": sha256(client) if client.exists() else None,
        "openssl": openssl_text,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_count": os.cpu_count(),
    }


def main() -> int:
    project = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Run a randomised PQC TLS experiment")
    parser.add_argument("--config", type=pathlib.Path, default=project / "config/experiment.json")
    parser.add_argument("--client", type=pathlib.Path, default=project / "build/tls_bench_client")
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-cells", type=int, help="Run only the first N scheduled cells")
    args = parser.parse_args()

    config = load_config(args.config)
    planned = schedule(config)
    if args.max_cells is not None:
        if args.max_cells < 1:
            parser.error("--max-cells must be positive")
        planned = planned[: args.max_cells]

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output or project / "results" / f"{config['experiment_id']}-{run_id}"
    raw_dir = output_dir / "raw"
    if not args.dry_run:
        raw_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "config.snapshot.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(environment_manifest(config, args.config, args.client), indent=2) + "\n",
            encoding="utf-8",
        )

    endpoint = config["endpoint"]
    execution = config["execution"]
    backend = config["network_backend"]
    schedule_records: list[dict[str, Any]] = []

    for ordinal, (batch, cell) in enumerate(planned, start=1):
        batch_id = f"batch-{batch:03d}"
        record = {
            "ordinal": ordinal,
            "batch_id": batch_id,
            "cell_id": cell.identifier,
            "group": cell.group,
            "rtt_ms": cell.rtt_ms,
            "loss_percent_each_direction": cell.loss_percent,
        }
        netem_commands = apply_netem(config, cell, args.dry_run)
        record["netem_commands"] = [shlex.join(item) for item in netem_commands]
        record["netem_observed"] = verify_netem(config, args.dry_run)

        client_command = [
            "sudo", "ip", "netns", "exec", backend["client_namespace"],
            str(args.client.resolve()),
            "--host", str(endpoint["host"]),
            "--port", str(endpoint["port"]),
            "--server-name", str(endpoint["server_name"]),
            "--ca-file", str((project / endpoint["ca_file"]).resolve()),
            "--group", cell.group,
            "--batch-id", batch_id,
            "--cell-id", cell.identifier,
            "--warmups", str(execution["warmup_handshakes_per_cell"]),
            "--attempts", str(execution["recorded_handshakes_per_cell"]),
            "--timeout-ms", str(execution["timeout_ms"]),
        ]
        record["client_command"] = shlex.join(client_command)
        schedule_records.append(record)

        if args.dry_run:
            print(f"{ordinal:04d} {batch_id} {cell.identifier}")
        else:
            raw_path = raw_dir / f"{batch_id}__{cell.identifier}.jsonl"
            started = time.monotonic()
            with raw_path.open("x", encoding="utf-8") as raw_output:
                completed = subprocess.run(
                    client_command,
                    text=True,
                    stdout=raw_output,
                    stderr=subprocess.PIPE,
                )
            record["duration_seconds"] = time.monotonic() - started
            record["exit_code"] = completed.returncode
            record["stderr"] = completed.stderr
            record["raw_sha256"] = sha256(raw_path)
            (output_dir / "schedule.json").write_text(
                json.dumps(schedule_records, indent=2) + "\n", encoding="utf-8"
            )
            if completed.returncode != 0:
                raise RuntimeError(f"Client failed for {cell.identifier}: {completed.stderr}")
            time.sleep(execution["pause_between_cells_ms"] / 1000.0)

    if args.dry_run:
        print(f"Planned {len(planned)} cells; output would be {output_dir}")
    else:
        print(f"Completed {len(planned)} cells; results: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
