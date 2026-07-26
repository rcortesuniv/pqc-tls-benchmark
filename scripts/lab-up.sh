#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
openssl_prefix="${OPENSSL_PREFIX:-/opt/openssl-3.5.7}"
openssl_bin="${openssl_prefix}/bin/openssl"
client_ns="pqcbench-client"
server_ns="pqcbench-server"
client_if="pqcbench-c"
server_if="pqcbench-s"
runtime_dir="${project_dir}/runtime"

if [[ ! -x "${project_dir}/build/tls_bench_client" ]]; then
  echo "Build the benchmark client first: make OPENSSL_PREFIX=${openssl_prefix}" >&2
  exit 1
fi
if [[ ! -f "${project_dir}/certs/server.crt" ]]; then
  OPENSSL_BIN="${openssl_bin}" "${project_dir}/scripts/generate-certs.sh"
fi
if sudo ip netns list | awk '{print $1}' | grep -Fxq "${client_ns}"; then
  echo "Lab namespace ${client_ns} already exists; run scripts/lab-down.sh first." >&2
  exit 1
fi

mkdir -p "${runtime_dir}"
sudo ip netns add "${client_ns}"
sudo ip netns add "${server_ns}"
sudo ip link add "${client_if}" type veth peer name "${server_if}"
sudo ip link set "${client_if}" netns "${client_ns}"
sudo ip link set "${server_if}" netns "${server_ns}"
sudo ip -n "${client_ns}" address add 10.203.0.1/30 dev "${client_if}"
sudo ip -n "${server_ns}" address add 10.203.0.2/30 dev "${server_if}"
sudo ip -n "${client_ns}" link set lo up
sudo ip -n "${server_ns}" link set lo up
sudo ip -n "${client_ns}" link set "${client_if}" up
sudo ip -n "${server_ns}" link set "${server_if}" up

sudo ip netns exec "${server_ns}" \
  env LD_LIBRARY_PATH="${openssl_prefix}/lib64:${openssl_prefix}/lib" \
  "${openssl_bin}" s_server \
  -accept 10.203.0.2:4433 \
  -tls1_3 \
  -groups "X25519:MLKEM768:X25519MLKEM768" \
  -cert "${project_dir}/certs/server.crt" \
  -key "${project_dir}/certs/server.key" \
  -no_cache -quiet \
  >"${runtime_dir}/server.log" 2>&1 &
server_launcher_pid=$!
printf '%s\n' "${server_launcher_pid}" >"${runtime_dir}/server-launcher.pid"

for _ in $(seq 1 40); do
  if sudo ip netns exec "${client_ns}" \
    bash -c 'exec 3<>/dev/tcp/10.203.0.2/4433' 2>/dev/null; then
    for group in X25519 MLKEM768 X25519MLKEM768; do
      if ! sudo ip netns exec "${client_ns}" \
        "${project_dir}/build/tls_bench_client" \
        --host 10.203.0.2 --port 4433 --server-name pqc-bench.local \
        --ca-file "${project_dir}/certs/ca.crt" --group "${group}" \
        --batch-id readiness --cell-id "readiness-${group}" \
        --warmups 0 --attempts 1 --timeout-ms 5000 \
        >"${runtime_dir}/readiness-${group}.jsonl"; then
        echo "TLS readiness test failed for ${group}; inspect runtime/server.log." >&2
        exit 1
      fi
      if ! grep -Fq '"status":"success"' "${runtime_dir}/readiness-${group}.jsonl"; then
        echo "TLS group verification failed for ${group}; inspect readiness evidence." >&2
        exit 1
      fi
    done
    echo "PQC TLS benchmark lab is ready and all experimental groups were verified."
    exit 0
  fi
  sleep 0.1
done

echo "Server did not become ready; inspect runtime/server.log." >&2
exit 1
