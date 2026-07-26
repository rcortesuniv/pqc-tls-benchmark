#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="${PQC_BENCH_IMAGE:-pqc-tls-bench:3.5.7}"
cert_volume="${PQC_BENCH_CERT_VOLUME:-pqc-tls-bench-certs}"
staging_container="pqcbench-cert-stage-$$"

cleanup_staging_container() {
  if [[ -n "${staging_container}" ]]; then
    docker rm --force "${staging_container}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_staging_container EXIT

if ! docker image inspect "${image}" >/dev/null 2>&1; then
  docker build --tag "${image}" "${project_dir}"
fi
if [[ ! -f "${project_dir}/certs/server.crt" ]]; then
  "${project_dir}/scripts/generate-certs.sh"
fi
docker volume create "${cert_volume}" >/dev/null
docker create --name "${staging_container}" \
  --mount "type=volume,source=${cert_volume},target=/certs" \
  "${image}" /bin/true >/dev/null
for certificate in ca.crt server.crt server.key; do
  docker cp "${project_dir}/certs/${certificate}" "${staging_container}:/certs/${certificate}"
done
docker rm "${staging_container}" >/dev/null
staging_container=""
docker compose --project-directory "${project_dir}" up --detach --wait
for group in X25519 MLKEM768 X25519MLKEM768; do
  docker compose --project-directory "${project_dir}" exec -T client \
    /usr/local/bin/tls_bench_client --host server --port 4433 --server-name pqc-bench.local \
    --ca-file /certs/ca.crt --group "${group}" --batch-id readiness \
    --cell-id "container-readiness-${group}" --warmups 0 --attempts 1 --timeout-ms 5000 \
    | grep -Fq '"status":"success"'
done
echo "Fixed-resource container lab is ready."
