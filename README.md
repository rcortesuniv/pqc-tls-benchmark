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
- TLS socket-BIO byte counts, process CPU time and peak-RSS evidence for explanatory analysis.
- A 36-cell matrix: 3 groups × 4 RTT levels × 3 per-direction loss levels.
- Seeded random order within each complete batch.
- Symmetric Linux network emulation using isolated network namespaces.
- Per-cell append-only JSONL, frozen schedules, configuration snapshots,
  environment metadata and SHA-256 integrity manifests.
- Batch-cell summaries, primary hybrid-minus-classical deltas, bootstrap
  intervals, autocorrelation diagnostics and Holm-adjusted paired contrasts.

The measurement boundary and field semantics are documented in
[`docs/measurement-boundary.md`](docs/measurement-boundary.md) and
[`docs/data-dictionary.md`](docs/data-dictionary.md). A live
[`protocol traceability matrix`](docs/protocol-traceability.md) shows what is
implemented, partial or still pending.

## Status

This artefact implements the roadmap's collection, explanatory and analysis
tooling. It is suitable for a **pilot**, not yet definitive data collection.
The definitive study must still wait for supervisor feedback, ethics screening,
pilot-calibrated settings and a frozen analysis plan. Tooling does not make
those research-governance decisions automatically.

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

For the fixed-resource backend, use `scripts/container-lab-up.sh`. The Compose
definition pins each endpoint to one CPU, 1 GiB memory and 256 processes;
change those values only before a new pilot and preserve the updated
configuration as evidence. After it is started, use the same randomised runner
with `scripts/run-experiment.py --backend container`; resource observations in
that mode describe the Compose launcher, while the endpoint resource boundary
is enforced by Docker's configured limits.

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

`lab-up.sh` verifies connectivity and performs one exact-group handshake for
each experimental group before reporting readiness. Calibrate a configured
profile independently before a pilot cell, for example:

```bash
scripts/calibrate-network.py --expected-rtt-ms 50 --expected-loss-percent 0.5
```

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

The runner prints a start and completion line for every cell. Do not type its
`Completed ... results: ...` line into the shell: it is program output. When a
run finishes, use the literal result directory printed by the runner, for
example:

```bash
analysis/summarise.py results/pqc-tls-pilot-20260727T120000Z
```

If a run started by the current version is interrupted, its partial cell output
is retained under `interrupted/` and its frozen schedule records the event. Do
not analyse that incomplete directory until it has been resumed successfully:

```bash
scripts/run-experiment.py --backend container \
  --output results/pqc-tls-pilot-20260727T120000Z --resume
```

Resume is guarded: the configuration, schedule and client binary must match
their frozen hashes. Older interrupted directories whose partial output was
written directly into `raw/` cannot be resumed safely and must be retained as
invalid pilot evidence before starting a fresh run.

## Analyse a run

```bash
analysis/summarise.py results/pqc-tls-pilot-20260727T120000Z
```

The script creates:

- `analysis/batch_cell_summary.csv`
- `analysis/primary_batch_deltas.csv`
- `analysis/validation.json`

The primary CSV contains paired within-batch median differences between
`X25519MLKEM768` and `X25519` for each network condition. Individual
handshakes remain nested subsamples and are not treated as independent
confirmatory units.

The script also writes `pairwise_batch_deltas.csv`,
`confirmatory_analysis.json` and a strict `validation.json`. The confirmatory
report uses batch-level percentile bootstrap intervals, lag-1 autocorrelation
diagnostics, paired sign-randomisation tests and Holm adjustment. It fails if
the frozen schedule is incomplete, raw records are duplicated/impossible, or
an integrity hash no longer matches.

`batch_cell_summary.csv` includes p95 and p99 latency in addition to the
median, mean and dispersion fields. Use these tail measures when interpreting
loss, since a cell median can remain stable while a minority of handshakes
retransmit.

The draft definitive configuration and its freeze/calibration checklist are in
[`docs/definitive-run.md`](docs/definitive-run.md). It deliberately keeps the
existing pilot results separate from a future confirmatory collection.

## Explore results in a browser

Generate a self-contained dashboard after collection:

```bash
analysis/dashboard.py results/pqc-tls-pilot-20260727T100719Z
```

It writes `analysis/dashboard.html` within that result directory and provides
interactive group, RTT and loss filters, latency charts, directional byte
summaries and batch-aware contrast outputs. See
[`docs/results-dashboard.md`](docs/results-dashboard.md) for Codespaces viewing
instructions.

When the supplied Codespaces development container is rebuilt, it starts a
private dashboard server on port 8000 automatically. The server renders the
newest result at `/dashboard.html` and refreshes it when the page is opened.

## Explanatory workloads

Run fixed-concurrency throughput separately from latency collection:

```bash
scripts/run-throughput.py --group X25519MLKEM768 --workers 4 --handshakes-per-worker 100
```

The client runner records child CPU time and observed peak RSS for each cell.
For cryptographic-only comparison, build and run:

```bash
build/pqc_microbench --iterations 1000
```

For transport-byte evidence, capture a cell and parse it with `tshark`:

```bash
scripts/capture-traffic.sh results/pilot/capture.pcap runtime/capture.pid
# run the selected cell, then: sudo kill "$(cat runtime/capture.pid)"
analysis/parse-pcap.py results/pilot/capture.pcap --output results/pilot/transport_bytes.csv
```

The capture parser reports TCP payload bytes by direction; it deliberately does
not relabel TLS socket-BIO bytes as transport bytes.

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
