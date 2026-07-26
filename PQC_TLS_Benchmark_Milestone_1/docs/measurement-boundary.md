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
the OpenSSL/socket boundary. These are not Ethernet, IP or TCP byte counts; a
packet-capture module will be needed when transport-layer attribution is added.

The current runner applies half the configured round-trip delay to each
direction. The configured loss percentage is also applied independently in
each direction, and is therefore described explicitly as
`loss_percent_each_direction`.

