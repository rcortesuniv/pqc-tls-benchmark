# Protocol-to-implementation traceability

| Preliminary protocol requirement | Initial implementation | Status |
| --- | --- | --- |
| OpenSSL 3.5.x native groups | 3.5.7 build script, Dockerfile and environment check | Implemented; integration build pending on target Linux host |
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
| Environment and integrity evidence | Config snapshot, manifest and SHA-256 hashes | Implemented |
| Batch as confirmatory unit | Per-batch cell medians and paired batch deltas | Implemented |
| CPU core/resource controls | Planned container backend and host monitoring | Not yet implemented |
| Independently verified network profile | Captures applied `tc` state; active calibration still required | Partial |
| Throughput under fixed concurrency | Separate workload required | Not yet implemented |
| CPU and peak memory | Batch/process collectors required | Not yet implemented |
| Transport bytes/fragmentation | TLS BIO bytes implemented; packet capture still required | Partial |
| Pure cryptographic microbenchmarks | ML-KEM and X25519 operation harness required | Not yet implemented |
| Batch-aware uncertainty and autocorrelation | Confirmatory analysis module required after pilot | Not yet implemented |

This table should be updated whenever the protocol or implementation changes.
It prevents claims in the dissertation from exceeding what the artefact
actually measures.

