# Protocol-to-implementation traceability

| Preliminary protocol requirement | Initial implementation | Status |
| --- | --- | --- |
| OpenSSL 3.5.x native groups | 3.5.7 build script, Dockerfile and environment check | Implemented; target-Linux integration still required |
| X25519, MLKEM768, X25519MLKEM768 | Exact single-group offer and post-handshake group verification | Implemented |
| Full TLS 1.3 handshakes | TLS 1.3 min/max fixed; new TCP and `SSL` object per attempt; cache disabled | Implemented |
| Client-side monotonic boundary | `CLOCK_MONOTONIC` immediately around `SSL_connect()` | Implemented |
| 0/20/50/100 ms RTT | Half the RTT applied on each endpoint egress | Implemented |
| 0/0.5/1% symmetric loss | Configured percentage applied independently per direction | Implemented |
| Complete cell set per batch | Cartesian matrix regenerated and shuffled for every batch | Implemented |
| Seeded randomisation | Dedicated deterministic PRNG seeded from frozen JSON | Implemented |
| Warm-ups excluded | Warm-up loop produces no raw observations | Implemented |
| Failures retained | TCP/TLS/verification outcomes recorded explicitly | Implemented |
| Append-only machine-readable raw data | Exclusive-create per-cell JSONL files | Implemented |
| Environment and integrity evidence | Frozen schedule before the first cell, provenance manifest and SHA-256 integrity manifest | Implemented |
| Interruptible long-run collection | Per-cell progress, interrupted-state schedule evidence, retained partial output and hash-guarded resume | Implemented for runs created by the current runner version |
| Batch as confirmatory unit | Per-batch cell medians and paired batch deltas | Implemented |
| CPU core/resource controls | Fixed-CPU/memory/PID Compose backend | Implemented; validate limits on target Docker host |
| Independently verified network profile | `tc` state plus independent namespace ping calibration | Implemented; perform and retain calibration evidence per pilot profile |
| Throughput under fixed concurrency | Separate `run-throughput.py` workload | Implemented |
| CPU and peak memory | Per-cell child CPU/context-switch and Linux process-tree peak-RSS collector | Implemented; sampled peak RSS is evidence, not a profiler |
| Transport bytes/fragmentation | TLS BIO counts plus namespace capture and `tshark` TCP payload parser | Implemented; capture must be started per selected cell |
| Pure cryptographic microbenchmarks | ML-KEM keygen/encapsulation/decapsulation and X25519 keygen/derive harness | Implemented; run on target OpenSSL build |
| Batch-aware uncertainty and autocorrelation | Completeness/integrity gate, batch bootstrap, lag-1 diagnostic, paired randomisation and Holm correction | Implemented |

This table should be updated whenever the protocol or implementation changes.
It prevents claims in the dissertation from exceeding what the artefact
actually measures.
