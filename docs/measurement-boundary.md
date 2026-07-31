# Measurement boundary

The primary endpoint is measured in the custom C client:

1. Resolve the configured address and establish a fresh TCP connection.
2. Create a fresh `SSL` object with TLS 1.3 only and session caching disabled.
3. Restrict the offered group to exactly one experimental group.
4. Start `CLOCK_MONOTONIC` immediately before `SSL_connect()`.
5. Stop the clock immediately after `SSL_connect()` returns.
6. Verify the negotiated group using `SSL_get0_group_name()`.
7. Record the observation whether it succeeded, failed, timed out or mismatched.
8. Destroy the connection and repeat with a new TCP and TLS state.

This excludes DNS and TCP setup from handshake latency while retaining setup
failures separately. The socket BIO callback counts TLS record bytes crossing
the OpenSSL/socket boundary in each direction. These are not Ethernet, IP or
TCP byte counts; a packet-capture module will be needed when transport-layer
attribution is added. Successful handshakes with no recorded outbound TLS bytes
are treated as an instrumentation failure by the validation gate.

OpenSSL reports canonical group names in lowercase, whereas the configured
CLI names use the conventional uppercase spelling. Verification therefore uses
case-insensitive equality while still requiring the complete group name to
match.

The current runner applies half the configured round-trip delay to each
direction. The configured loss percentage is also applied independently in
each direction, and is therefore described explicitly as
`loss_percent_each_direction`.

CPU time and peak RSS are cell-level process evidence, not part of the latency
endpoint. Packet captures are collected and parsed separately; TCP payload
bytes must not be conflated with the TLS socket-BIO byte counters.

## CPU scheduling and the noise floor

Reported effects (the primary contrast, and most exploratory contrasts) are on
the order of a few hundred microseconds. Without CPU isolation, the OS
scheduler can migrate the client or server process between cores mid-run,
adding jitter of a similar or larger magnitude — a real risk to validity at
this effect size, not a theoretical one.

`scripts/lab-up.sh` and `scripts/run-experiment.py` pin the server and client
to fixed cores with `taskset` by default (server: CPU 0, client: CPU 1;
override with `PQC_SERVER_CPU` / `PQC_CLIENT_CPU`, disable with
`PQC_CPU_PINNING=0`). The container backend does the same natively via
`cpuset` in `compose.yaml`. This is pinning, not isolation: it stops
cross-core migration, but it does **not** reserve the core exclusively —
unrelated host processes, interrupts, and (in a shared/virtualized
environment such as a Codespace) other tenants on the same physical core can
still preempt it. `isolcpus`/`nohz_full` kernel boot parameters or a
dedicated bare-metal host would be needed to go further; that is out of
scope for this tooling.

Because pinning alone cannot prove the noise floor is smaller than a reported
effect, `scripts/calibrate-noise-floor.py` measures it directly: it runs
repeated handshakes of a single group, splits them into two interleaved arms,
and puts the arm-vs-arm delta through the exact same bootstrap CI,
sign-permutation test and TOST equivalence test used for real contrasts.
Since both arms are the same group, any reported effect there is pure
measurement noise — run it (with the same `--batches` as the real
experiment) and compare its mean and CI against the primary contrast's
before treating a small real effect as more than noise.
