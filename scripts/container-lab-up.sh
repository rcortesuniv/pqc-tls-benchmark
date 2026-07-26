#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${PQC_BENCH_IMAGE:-pqc-tls-bench:3.5.7}"

if ! docker image inspect "${image}" >/dev/null 2>&1; then
  docker build --tag "${image}" "${project_dir}"
fi
if [[ ! -f "${project_dir}/certs/server.crt" ]]; then
  "${project_dir}/scripts/generate-certs.sh"
fi
docker compose --project-directory "${project_dir}" up --detach --wait
for group in X25519 MLKEM768 X25519MLKEM768; do
  docker compose --project-directory "${project_dir}" exec -T client \
    /usr/local/bin/tls_bench_client --host server --port 4433 --server-name pqc-bench.local \
    --ca-file /certs/ca.crt --group "${group}" --batch-id readiness \
    --cell-id "container-readiness-${group}" --warmups 0 --attempts 1 --timeout-ms 5000 \
    | grep -Fq '"status":"success"'
done
echo "Fixed-resource container lab is ready."
