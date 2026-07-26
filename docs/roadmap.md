# Implementation roadmap

## Milestone 1 — executable core

- Pinned OpenSSL 3.5 LTS build.
- Exact-group TLS 1.3 client.
- Seeded block randomisation.
- Symmetric network emulation.
- Append-only raw JSONL and integrity hashes.
- Batch-cell summaries and primary hybrid/classical deltas.

## Milestone 2 — pilot hardening

- Container backend with fixed CPU allocation and resource limits.
- Independently measured delay/loss calibration.
- Server readiness and negotiated-group self-tests.
- Thermal/background-load monitors.
- Pilot-based timeout, warm-up and batch-count decisions.

Implemented as tooling: `compose.yaml` and the container scripts provide fixed
resource limits; `lab-up.sh` verifies every negotiated group; calibration is
recorded through `calibrate-network.py`; and the runner freezes its schedule
and preserves cell-level resource evidence. The numeric settings are still
provisional until a pilot has been reviewed.

## Milestone 3 — explanatory measures

- Packet capture and transport-byte parsing.
- Batch/process CPU and peak-RSS collection.
- Explicit fixed-concurrency throughput workload.
- ML-KEM key-generation, encapsulation and decapsulation microbenchmarks.

Implemented as separate workloads so they do not contaminate the primary
latency endpoint: runner resource evidence, `capture-traffic.sh` plus
`parse-pcap.py`, `run-throughput.py`, and `pqc_microbench`.

## Milestone 4 — confirmatory analysis

- Completeness and impossible-value checks.
- Batch-aware bootstrap intervals.
- Autocorrelation diagnostics.
- Multiplicity-controlled pairwise contrasts.
- Frozen acceptance-threshold sensitivity analysis.

Implemented in `analysis/summarise.py`: integrity/completeness and
impossible-value checks, batch-level bootstrap intervals, lag-1 diagnostics,
paired sign-randomisation contrasts with Holm adjustment, and configured
threshold sensitivity. These functions execute a frozen plan; they do not
license post-hoc threshold selection.

The definitive experiment must not begin until the pilot settings and analysis
plan are frozen and supervisor/ethics requirements are known.
