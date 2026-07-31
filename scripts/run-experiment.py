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
import re
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
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
    if not isinstance(config["groups"], list) or not config["groups"]:
        raise ValueError("groups must be a non-empty list")
    if not all(isinstance(group, str) and re.fullmatch(r"[A-Za-z0-9-]+", group) for group in config["groups"]):
        raise ValueError("TLS group names may contain only letters, digits and hyphens")
    if len(set(config["groups"])) != len(config["groups"]):
        raise ValueError("TLS group names must be unique")
    if not isinstance(config["execution"], dict) or not isinstance(config["network"], dict):
        raise ValueError("execution and network must be objects")
    if not isinstance(config["execution"].get("batches"), int) or config["execution"]["batches"] < 1:
        raise ValueError("execution.batches must be at least 1")
    execution = config["execution"]
    for key in ("warmup_handshakes_per_cell", "recorded_handshakes_per_cell", "timeout_ms"):
        if isinstance(execution.get(key), bool) or not isinstance(execution.get(key), int) or execution[key] < 0:
            raise ValueError(f"execution.{key} must be a non-negative integer")
    if execution["recorded_handshakes_per_cell"] < 1:
        raise ValueError("execution.recorded_handshakes_per_cell must be at least 1")
    if execution["timeout_ms"] < 1:
        raise ValueError("execution.timeout_ms must be at least 1")
    if not isinstance(config["network"].get("rtt_ms"), list) or not config["network"]["rtt_ms"]:
        raise ValueError("network.rtt_ms must be a non-empty list")
    if not isinstance(config["network"].get("loss_percent_each_direction"), list) or not config["network"]["loss_percent_each_direction"]:
        raise ValueError("network.loss_percent_each_direction must be a non-empty list")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 for value in config["network"]["rtt_ms"]):
        raise ValueError("network.rtt_ms values must be non-negative")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100 for value in config["network"]["loss_percent_each_direction"]):
        raise ValueError("network.loss_percent_each_direction values must be between 0 and 100")
    if not isinstance(config["endpoint"], dict) or not all(isinstance(config["endpoint"].get(key), (str, int)) for key in ("host", "port", "server_name", "ca_file")):
        raise ValueError("endpoint must define host, port, server_name and ca_file")
    backend = config.get("network_backend")
    if not isinstance(backend, dict) or backend.get("type") != "netns":
        raise ValueError("network_backend.type must be netns")
    for key in ("client_namespace", "server_namespace", "client_interface", "server_interface"):
        value = backend.get(key)
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
            raise ValueError(f"network_backend.{key} is invalid")
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


def compose_exec(project: pathlib.Path, service: str, command: list[str]) -> list[str]:
    return ["docker", "compose", "--project-directory", str(project), "exec", "-T", service, *command]


def apply_container_netem(project: pathlib.Path, cell: Cell, dry_run: bool) -> list[list[str]]:
    one_way_delay = cell.rtt_ms / 2.0
    commands: list[list[str]] = []
    for service in ("client", "server"):
        netem = ["tc", "qdisc", "replace", "dev", "eth0", "root", "netem"]
        if one_way_delay:
            netem.extend(["delay", f"{one_way_delay:g}ms"])
        if cell.loss_percent:
            netem.extend(["loss", f"{cell.loss_percent:g}%"])
        if not one_way_delay and not cell.loss_percent:
            netem.extend(["delay", "0ms"])
        command = compose_exec(project, service, netem)
        commands.append(command)
        if not dry_run:
            run(command)
    return commands


def verify_container_netem(project: pathlib.Path, dry_run: bool) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for service in ("client", "server"):
        command = compose_exec(project, service, ["tc", "qdisc", "show", "dev", "eth0"])
        evidence[service] = shlex.join(command) if dry_run else run(command, capture=True).stdout.strip()
    return evidence


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    """Atomically replace provenance files; raw observations remain create-only."""
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as stream:
        stream.write(json.dumps(value, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        temporary = pathlib.Path(stream.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def child_usage() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "user_cpu_seconds": usage.ru_utime,
        "system_cpu_seconds": usage.ru_stime,
        "involuntary_context_switches": float(usage.ru_nivcsw),
        "voluntary_context_switches": float(usage.ru_nvcsw),
    }


def usage_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    return {key: max(0.0, after[key] - before[key]) for key in before}


def process_tree_peak_rss_kib(pid: int) -> int | None:
    """Return the highest observed VmHWM for a Linux process tree.

    `sudo ip netns exec` introduces short-lived wrapper processes, so sampling
    the tree rather than just the launcher avoids attributing only sudo's RSS.
    The value is evidence for a batch cell, not a per-handshake measurement.
    """
    if not sys.platform.startswith("linux"):
        return None
    pending = [pid]
    seen: set[int] = set()
    peak = 0
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        status = pathlib.Path(f"/proc/{current}/status")
        children = pathlib.Path(f"/proc/{current}/task/{current}/children")
        try:
            for line in status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmHWM:"):
                    peak = max(peak, int(line.split()[1]))
            pending.extend(int(value) for value in children.read_text().split())
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return peak or None


def run_monitored(command: list[str], raw_output: Any) -> tuple[subprocess.CompletedProcess[str], dict[str, Any]]:
    started_usage = child_usage()
    with tempfile.SpooledTemporaryFile(max_size=1024 * 1024, mode="w+t", encoding="utf-8") as stderr_stream:
        process = subprocess.Popen(command, text=True, stdout=raw_output, stderr=stderr_stream)
        peak_rss_kib = 0
        while process.poll() is None:
            sampled = process_tree_peak_rss_kib(process.pid)
            if sampled:
                peak_rss_kib = max(peak_rss_kib, sampled)
            time.sleep(0.01)
        process.wait()
        stderr_stream.seek(0)
        stderr = stderr_stream.read()
        final_sample = process_tree_peak_rss_kib(process.pid)
        if final_sample:
            peak_rss_kib = max(peak_rss_kib, final_sample)
    return (
        subprocess.CompletedProcess(command, process.returncode, stderr=stderr),
        {
            "child_resource_usage": usage_delta(started_usage, child_usage()),
            "peak_rss_kib": peak_rss_kib or None,
        },
    )


def integrity_manifest(output_dir: pathlib.Path) -> dict[str, str]:
    paths = [
        output_dir / "config.snapshot.json",
        output_dir / "manifest.json",
        output_dir / "schedule.json",
        output_dir / "resume.json",
        *sorted((output_dir / "raw").glob("*.jsonl")),
        *sorted((output_dir / "interrupted").glob("*.jsonl")),
    ]
    return {str(path.relative_to(output_dir)): sha256(path) for path in paths if path.is_file()}


def cpu_pinning_plan() -> dict[str, Any]:
    """Decide whether to pin the client to a fixed core, mirroring lab-up.sh's
    server-side decision. Cross-core scheduler migration is jitter on the same
    order as the sub-millisecond effects this benchmark measures; see
    docs/measurement-boundary.md. Disable with PQC_CPU_PINNING=0."""
    if os.environ.get("PQC_CPU_PINNING", "1") == "0":
        return {"enabled": False, "reason": "disabled via PQC_CPU_PINNING=0"}
    if shutil.which("taskset") is None:
        return {"enabled": False, "reason": "taskset not found"}
    if (os.cpu_count() or 1) < 2:
        return {"enabled": False, "reason": "fewer than 2 CPUs available"}
    return {"enabled": True, "client_cpu": int(os.environ.get("PQC_CLIENT_CPU", "1"))}


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
        "cpu_pinning": cpu_pinning_plan(),
    }


def main() -> int:
    project = pathlib.Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Run a randomised PQC TLS experiment")
    parser.add_argument("--config", type=pathlib.Path, default=project / "config/experiment.json")
    parser.add_argument("--client", type=pathlib.Path, default=project / "build/tls_bench_client")
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backend", choices=("netns", "container"), help="Override the configured backend")
    parser.add_argument("--max-cells", type=int, help="Run only the first N scheduled cells")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted run created by this version; requires --output",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    backend_type = args.backend or config["network_backend"]["type"]
    planned = schedule(config)
    if args.max_cells is not None:
        if args.max_cells < 1:
            parser.error("--max-cells must be positive")
        planned = planned[: args.max_cells]

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.resume and args.dry_run:
        parser.error("--resume cannot be combined with --dry-run")
    if args.resume and args.output is None:
        parser.error("--resume requires --output RESULT_DIRECTORY")

    output_dir = args.output or project / "results" / f"{config['experiment_id']}-{run_id}"
    raw_dir = output_dir / "raw"
    if args.resume:
        if not output_dir.is_dir() or not (output_dir / "schedule.json").is_file():
            raise RuntimeError(f"Cannot resume: {output_dir} has no frozen schedule")
        manifest_path = output_dir / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"Cannot resume: {output_dir} has no environment manifest")
        original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if original_manifest.get("config_sha256") != sha256(args.config):
            raise RuntimeError("Cannot resume: the current configuration differs from the frozen snapshot")
        original_client_hash = original_manifest.get("client_sha256")
        current_client_hash = sha256(args.client) if args.client.exists() else None
        if original_client_hash != current_client_hash:
            raise RuntimeError("Cannot resume: the client binary differs from the frozen environment")
    elif not args.dry_run:
        raw_dir.mkdir(parents=True, exist_ok=False)
        write_json(output_dir / "config.snapshot.json", config)
        write_json(output_dir / "manifest.json", environment_manifest(config, args.config, args.client))

    endpoint = config["endpoint"]
    execution = config["execution"]
    backend = config["network_backend"]
    cpu_pinning = cpu_pinning_plan()
    expected_schedule: list[dict[str, Any]] = []
    for ordinal, (batch, cell) in enumerate(planned, start=1):
        batch_id = f"batch-{batch:03d}"
        expected_schedule.append(
            {
                "ordinal": ordinal,
                "batch_id": batch_id,
                "cell_id": cell.identifier,
                "group": cell.group,
                "rtt_ms": cell.rtt_ms,
                "loss_percent_each_direction": cell.loss_percent,
                "state": "pending",
            }
        )
    if args.resume:
        schedule_records = json.loads((output_dir / "schedule.json").read_text(encoding="utf-8"))
        expected_identity = [
            (record["ordinal"], record["batch_id"], record["cell_id"])
            for record in expected_schedule
        ]
        actual_identity = [
            (record.get("ordinal"), record.get("batch_id"), record.get("cell_id"))
            for record in schedule_records
        ]
        if actual_identity != expected_identity:
            raise RuntimeError("Cannot resume: the frozen schedule does not match the requested plan")
        for record in schedule_records:
            if record.get("state") != "completed":
                raw_path = raw_dir / f"{record['batch_id']}__{record['cell_id']}.jsonl"
                if raw_path.exists():
                    raise RuntimeError(
                        f"Cannot safely resume: unfinished cell has raw data at {raw_path}. "
                        "Start a fresh run instead."
                    )
        resume_path = output_dir / "resume.json"
        events = json.loads(resume_path.read_text(encoding="utf-8")) if resume_path.exists() else []
        events.append({
            "resumed_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "client_sha256": current_client_hash,
        })
        write_json(resume_path, events)
    else:
        schedule_records = expected_schedule
    if not args.dry_run and not args.resume:
        # Freeze the entire order before the first perturbation or handshake.
        write_json(output_dir / "schedule.json", schedule_records)

    active_record: dict[str, Any] | None = None
    active_partial: pathlib.Path | None = None
    try:
        for ordinal, (batch, cell) in enumerate(planned, start=1):
            batch_id = f"batch-{batch:03d}"
            record = schedule_records[ordinal - 1]
            if args.resume and record.get("state") == "completed":
                continue
            active_record = record
            active_partial = None
            if not args.dry_run:
                record["state"] = "running"
                record["started_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
                write_json(output_dir / "schedule.json", schedule_records)
                print(f"[{ordinal:04d}/{len(planned):04d}] starting {batch_id} {cell.identifier}", flush=True)
            if backend_type == "netns":
                netem_commands = apply_netem(config, cell, args.dry_run)
                netem_observed = verify_netem(config, args.dry_run)
            else:
                netem_commands = apply_container_netem(project, cell, args.dry_run)
                netem_observed = verify_container_netem(project, args.dry_run)
            record["netem_commands"] = [shlex.join(item) for item in netem_commands]
            record["netem_observed"] = netem_observed

            if backend_type == "netns":
                client_command = ["sudo", "ip", "netns", "exec", backend["client_namespace"]]
                if cpu_pinning["enabled"]:
                    client_command += ["taskset", "-c", str(cpu_pinning["client_cpu"])]
                client_command += [
                    str(args.client.resolve()), "--host", str(endpoint["host"]),
                    "--port", str(endpoint["port"]), "--server-name", str(endpoint["server_name"]),
                    "--ca-file", str((project / endpoint["ca_file"]).resolve()),
                ]
            else:
                client_command = compose_exec(project, "client", [
                    "/usr/local/bin/tls_bench_client", "--host", "server", "--port", str(endpoint["port"]),
                    "--server-name", str(endpoint["server_name"]), "--ca-file", "/certs/ca.crt",
                ])
            client_command.extend([
                "--group", cell.group, "--batch-id", batch_id, "--cell-id", cell.identifier,
                "--warmups", str(execution["warmup_handshakes_per_cell"]),
                "--attempts", str(execution["recorded_handshakes_per_cell"]),
                "--timeout-ms", str(execution["timeout_ms"]),
            ])
            record["client_command"] = shlex.join(client_command)
            if args.dry_run:
                print(f"{ordinal:04d} {batch_id} {cell.identifier}")
            else:
                raw_path = raw_dir / f"{batch_id}__{cell.identifier}.jsonl"
                interrupted_dir = output_dir / "interrupted"
                interrupted_dir.mkdir(exist_ok=True)
                active_partial = interrupted_dir / f"{raw_path.stem}__attempt-{ordinal:04d}.jsonl"
                started = time.monotonic()
                with active_partial.open("x", encoding="utf-8") as raw_output:
                    completed, metrics = run_monitored(client_command, raw_output)
                active_partial.replace(raw_path)
                active_partial = None
                record["duration_seconds"] = time.monotonic() - started
                record.update(metrics)
                if backend_type == "container":
                    record["resource_evidence_scope"] = "docker-compose launcher; use Docker limits for endpoint isolation"
                record["exit_code"] = completed.returncode
                record["stderr"] = completed.stderr
                record["raw_sha256"] = sha256(raw_path)
                record["state"] = "completed" if completed.returncode == 0 else "client_failed"
                write_json(output_dir / "schedule.json", schedule_records)
                if completed.returncode != 0:
                    write_json(output_dir / "integrity.json", integrity_manifest(output_dir))
                    raise RuntimeError(f"Client failed for {cell.identifier}: {completed.stderr}")
                print(f"[{ordinal:04d}/{len(planned):04d}] completed {cell.identifier} in {record['duration_seconds']:.1f}s", flush=True)
                active_record = None
                time.sleep(execution["pause_between_cells_ms"] / 1000.0)
    except KeyboardInterrupt:
        if not args.dry_run and active_record is not None and active_record.get("state") != "completed":
            active_record["state"] = "interrupted"
            active_record["interrupted_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            if active_partial is not None and active_partial.exists():
                active_record["partial_raw_path"] = str(active_partial.relative_to(output_dir))
                active_record["partial_raw_sha256"] = sha256(active_partial)
            write_json(output_dir / "schedule.json", schedule_records)
            write_json(output_dir / "integrity.json", integrity_manifest(output_dir))
        print("Interrupted; schedule and partial evidence were preserved. Resume with --output RESULT_DIRECTORY --resume.", file=sys.stderr)
        return 130

    if args.dry_run:
        print(f"Planned {len(planned)} cells; output would be {output_dir}")
    else:
        write_json(output_dir / "integrity.json", integrity_manifest(output_dir))
        print(f"Completed {len(planned)} cells; results: {output_dir}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
