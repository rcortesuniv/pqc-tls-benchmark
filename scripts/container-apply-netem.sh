#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rtt_ms="${1:?Usage: container-apply-netem.sh RTT_MS LOSS_PERCENT}"
loss_percent="${2:?Usage: container-apply-netem.sh RTT_MS LOSS_PERCENT}"
one_way_delay="$(awk -v rtt="${rtt_ms}" 'BEGIN { printf "%g", rtt / 2 }')"

for service in client server; do
  args=(tc qdisc replace dev eth0 root netem)
  if [[ "${one_way_delay}" != "0" ]]; then args+=(delay "${one_way_delay}ms"); fi
  if [[ "${loss_percent}" != "0" ]]; then args+=(loss "${loss_percent}%"); fi
  if [[ ${#args[@]} -eq 7 ]]; then args+=(delay 0ms); fi
  docker compose --project-directory "${project_dir}" exec -T "${service}" "${args[@]}"
  docker compose --project-directory "${project_dir}" exec -T "${service}" tc qdisc show dev eth0
done
