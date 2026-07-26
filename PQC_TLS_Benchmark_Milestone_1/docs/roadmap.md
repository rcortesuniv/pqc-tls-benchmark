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

## Milestone 3 — explanatory measures

- Packet capture and transport-byte parsing.
- Batch/process CPU and peak-RSS collection.
- Explicit fixed-concurrency throughput workload.
- ML-KEM key-generation, encapsulation and decapsulation microbenchmarks.

## Milestone 4 — confirmatory analysis

- Completeness and impossible-value checks.
- Batch-aware bootstrap intervals.
- Autocorrelation diagnostics.
- Multiplicity-controlled pairwise contrasts.
- Frozen acceptance-threshold sensitivity analysis.

The definitive experiment must not begin until the pilot settings and analysis
plan are frozen and supervisor/ethics requirements are known.

