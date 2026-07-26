#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 OUTPUT_PCAP PID_FILE" >&2
  exit 2
fi
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pcap_path="$1"
pid_path="$2"
mkdir -p "$(dirname "${pcap_path}")" "$(dirname "${pid_path}")"

sudo ip netns exec pqcbench-client tcpdump -U -n -i pqcbench-c -w "${pcap_path}" 'tcp port 4433' &
capture_pid=$!
printf '%s\n' "${capture_pid}" >"${pid_path}"
echo "Capture started (PID ${capture_pid}). Stop with: sudo kill ${capture_pid}"
