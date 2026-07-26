#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
openssl_bin="${OPENSSL_BIN:-/opt/openssl-3.5.7/bin/openssl}"
cert_dir="${project_dir}/certs"

mkdir -p "${cert_dir}"
"${openssl_bin}" req -x509 -newkey rsa:3072 -sha256 -nodes \
  -days 30 \
  -subj "/CN=PQC TLS Benchmark Test CA" \
  -keyout "${cert_dir}/ca.key" \
  -out "${cert_dir}/ca.crt"
"${openssl_bin}" req -newkey rsa:3072 -sha256 -nodes \
  -subj "/CN=pqc-bench.local" \
  -addext "subjectAltName=DNS:pqc-bench.local" \
  -keyout "${cert_dir}/server.key" \
  -out "${cert_dir}/server.csr"
"${openssl_bin}" x509 -req -sha256 -days 30 \
  -in "${cert_dir}/server.csr" \
  -CA "${cert_dir}/ca.crt" \
  -CAkey "${cert_dir}/ca.key" \
  -CAcreateserial \
  -copy_extensions copy \
  -out "${cert_dir}/server.crt"
rm "${cert_dir}/server.csr" "${cert_dir}/ca.srl"
chmod 600 "${cert_dir}/ca.key" "${cert_dir}/server.key"

