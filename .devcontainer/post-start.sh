#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="${project_dir}/runtime"
mkdir -p "${log_dir}"

# A Codespace may be restarted without killing a previous post-start child.
# Stop only this project's prior dashboard server before launching a replacement.
pkill -f "${project_dir}/analysis/dashboard_server.py" >/dev/null 2>&1 || true
nohup python3 "${project_dir}/analysis/dashboard_server.py" --bind 0.0.0.0 --port 8000 \
  >"${log_dir}/dashboard-server.log" 2>&1 &
