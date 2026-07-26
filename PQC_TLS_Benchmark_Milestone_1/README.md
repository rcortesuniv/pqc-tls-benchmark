# PQC TLS Benchmark

An initial research artefact for reproducibly comparing classical, pure
post-quantum and hybrid TLS 1.3 key establishment:

- `X25519`
- `MLKEM768`
- `X25519MLKEM768`

The system follows the preliminary capstone protocol for **Design and
Performance Evaluation of a Hybrid Post-Quantum Secure Communication System**.
It is a laboratory benchmark, not a production TLS deployment or a new
cryptographic implementation.

## What is implemented

- OpenSSL 3.5.7 LTS build pinned to the current supported 3.5 line.
- Custom C client that times `SSL_connect()` after TCP establishment using
  `CLOCK_MONOTONIC`.
- Fresh TLS 1.3 handshake state for every attempt, with session caching off.
- Exact negotiated-group verification on every successful handshake.
- Separate recording of TCP, TLS and verification failures.
- TLS socket-BIO byte counts for explanatory analysis.
- A 36-cell matrix: 3 groups × 4 RTT levels × 3 per-direction loss levels.
- Seeded random order within each complete batch.
- Symmetric Linux network emulation using isolated network namespaces.
- Per-cell append-only JSONL, configuration snapshots, environment metadata
  and SHA-256 integrity hashes.
- Batch-cell summaries and the primary hybrid-minus-classical median delta.

The measurement boundary and field semantics are documented in
[`docs/measurement-boundary.md`](docs/measurement-boundary.md) and
[`docs/data-dictionary.md`](docs/data-dictionary.md). A live
[`protocol traceability matrix`](docs/protocol-traceability.md) shows what is
implemented, partial or still pending.

## Status

This is **Milestone 1: executable core**. It is suitable for software
development and pilot preparation, but not yet for definitive data collection.
The definitive study must wait for supervisor feedback, ethics screening,
pilot-based settings and a frozen analysis plan.

CPU/RSS attribution, fixed-concurrency throughput, packet capture,
microbenchmarks and batch-aware confidence intervals remain on the documented
[`roadmap`](docs/roadmap.md). The current native Linux network-namespace
backend will also be complemented by a fixed-resource container backend before
the definitive experiment.

## Requirements

- Native x86-64 Linux.
- `make`, a C compiler, Perl and curl.
- `iproute2` (`ip` and `tc`).
- `sudo` permission to create network namespaces and apply `netem`.
- Approximately 2 GB of free space while building OpenSSL.

The orchestration code itself uses only the Python 3 standard library.

## Build

Install the latest supported OpenSSL 3.5 LTS patch used by this artefact:

```bash
scripts/bootstrap-openssl.sh
```

The script downloads OpenSSL 3.5.7 and its published SHA-256 file from the
official GitHub release, verifies the archive, runs the upstream test suite and
installs to `/opt/openssl-3.5.7`.

Build and test the project:

```bash
make
make test
scripts/check-environment.py
```

After the build succeeds, the complete one-cell integration check is:

```bash
scripts/smoke-test.sh
```

An image definition is also included:

```bash
docker build --tag pqc-tls-bench:3.5.7 .
```

## Start the isolated lab

```bash
scripts/lab-up.sh
```

This creates two network namespaces joined by a dedicated veth pair, generates
a short-lived private test CA and server certificate, and starts an OpenSSL
TLS 1.3 server supporting the three experimental groups.

Stop the lab after use:

```bash
scripts/lab-down.sh
```

Traffic never leaves the isolated point-to-point namespace link.

## Inspect the randomised schedule

Always inspect a dry run before collecting pilot data:

```bash
scripts/run-experiment.py --dry-run
```

For a one-cell smoke test:

```bash
scripts/run-experiment.py --max-cells 1
```

The full provisional plan executes 10 batches × 36 cells × 100 recorded
handshakes, plus 20 unrecorded warm-ups per cell. These are planning values and
must not be treated as the final sample-size decision.

## Analyse a run

```bash
analysis/summarise.py results/<run-directory>
```

The script creates:

- `analysis/batch_cell_summary.csv`
- `analysis/primary_batch_deltas.csv`
- `analysis/validation.json`

The primary CSV contains paired within-batch median differences between
`X25519MLKEM768` and `X25519` for each network condition. Individual
handshakes remain nested subsamples and are not treated as independent
confirmatory units.

## Reproducibility rules

1. Do not edit raw JSONL after collection.
2. Preserve failed attempts and their phase.
3. Keep the configuration snapshot, manifest, schedule and hashes together.
4. Do not change warm-up, timeout, threshold or batch rules during a
   definitive run.
5. Record any interruption or environmental anomaly in a separate run log.
6. Re-run the full pilot after changes to OpenSSL, compiler flags, hardware,
   certificates, CPU allocation or measurement code.

## Safety and scope

The scripts operate only on namespaces named `pqcbench-client` and
`pqcbench-server`. Do not point the benchmark at an external host or a
production service. The generated CA and certificates are temporary laboratory
credentials and are intentionally excluded from version control.
