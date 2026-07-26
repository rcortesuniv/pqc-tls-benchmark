#!/usr/bin/env bash
set -euo pipefail

for namespace in pqcbench-client pqcbench-server; do
  if sudo ip netns list | awk '{print $1}' | grep -Fxq "${namespace}"; then
    mapfile -t namespace_pids < <(sudo ip netns pids "${namespace}")
    if ((${#namespace_pids[@]})); then
      sudo kill "${namespace_pids[@]}" 2>/dev/null || true
    fi
    sudo ip netns delete "${namespace}"
  fi
done
echo "PQC TLS benchmark lab stopped."

