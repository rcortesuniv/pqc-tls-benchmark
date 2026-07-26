# Data dictionary

Each recorded handshake is one JSON object in a per-cell `.jsonl` file. Warm-up
handshakes are executed but never written to the definitive raw dataset.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | string | Observation schema version. |
| `batch_id` | string | Temporally separated confirmatory batch. |
| `cell_id` | string | TLS-group and network-condition identifier. |
| `sequence` | integer | Recorded attempt order within the cell. |
| `timestamp_utc` | string | UTC wall-clock timestamp for provenance. |
| `requested_group` | string | Sole group offered by the client. |
| `status` | string | `success`, `failed`, `timeout`, or `group_mismatch`. |
| `failure_phase` | string/null | `tcp_connect`, `ssl_initialise`, `tls_handshake`, `verification`, or null. |
| `handshake_latency_ms` | number/null | Monotonic duration of `SSL_connect()` after TCP establishment. |
| `negotiated_group` | string/null | Group reported by OpenSSL after a successful handshake. |
| `cipher` | string/null | Negotiated TLS 1.3 cipher suite. |
| `tls_bytes_read` | integer | Bytes read at the TLS socket BIO during the measured connection. |
| `tls_bytes_written` | integer | Bytes written at the TLS socket BIO during the measured connection. |
| `openssl_error_code` | integer | Last OpenSSL error code when available; zero otherwise. |

TCP connection failures are retained but have no handshake latency because the
proposal's timing boundary starts only after TCP establishment. Analyses must
state explicitly whether operational reliability includes these transport
failures or uses only established-connection attempts.

Per-cell execution evidence is held in `schedule.json`, rather than duplicated
into every raw record: applied/observed netem state, command, duration, child
CPU/context-switch deltas, observed process-tree peak RSS, raw SHA-256 and
completion status. `integrity.json` covers the frozen schedule, provenance
files and every raw JSONL file.
