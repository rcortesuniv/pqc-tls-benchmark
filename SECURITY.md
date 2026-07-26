# Security policy

This repository is a laboratory artefact. Its generated certificates, network
namespaces and container configuration must not be used for production traffic
or exposed to untrusted networks.

## Supported baseline

Security fixes are made on the current `main` branch. The benchmark pins the
OpenSSL 3.5 LTS line and must be rebuilt whenever an upstream security patch is
released.

## Reporting a vulnerability

Do not publish exploitable details in a public issue. Contact the repository
owner privately with a minimal reproduction, affected revision and impact. Do
not include private keys, captures, result datasets or credentials in the
report.
