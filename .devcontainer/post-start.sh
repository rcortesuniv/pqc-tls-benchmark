#!/usr/bin/env bash
# Auto-serve the PQC TLS dashboard in the Codespace, and keep it healthy.
#
# Behaviour:
#   - launches one detached supervisor (this script with --supervise);
#   - starts the dashboard server on 0.0.0.0:8000 (overridable via env);
#   - pulls the latest main (fast-forward only, never discards local work)
#     so the server runs current committed code;
#   - restarts the server if it crashes;
#   - reloads the server when analysis/*.py changes (e.g. after a git pull),
#     so pushed fixes take effect without a manual restart.
set -uo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log_dir="${project_dir}/runtime"
mkdir -p "${log_dir}"
log="${log_dir}/dashboard-server.log"
sup_pidfile="${log_dir}/dashboard-supervisor.pid"
server="${project_dir}/analysis/dashboard_server.py"
port="${PQC_DASHBOARD_PORT:-8000}"
bind="${PQC_DASHBOARD_BIND:-0.0.0.0}"

ts() { date '+%FT%T%z'; }
log() { printf '[dashboard %s] %s\n' "$(ts)" "$*" >>"${log}"; }

# postStartCommand must not block Codespace startup: detach the supervisor.
if [ "${1:-}" != "--supervise" ]; then
  nohup bash "$0" --supervise >>"${log}" 2>&1 &
  log "supervisor launched (detached)"
  exit 0
fi

# --- supervisor body ---
# Replace any previous supervisor from an earlier post-start run.
if [ -f "${sup_pidfile}" ]; then
  prev="$(cat "${sup_pidfile}" 2>/dev/null || true)"
  if [ -n "${prev}" ] && [ "${prev}" != "$$" ] && kill -0 "${prev}" 2>/dev/null; then
    log "stopping previous supervisor (pid ${prev})"
    kill "${prev}" 2>/dev/null || true
    sleep 1
  fi
fi
pkill -f "${server}" >/dev/null 2>&1 || true
echo $$ >"${sup_pidfile}"
cleanup() {
  log "supervisor (pid $$) exiting"
  if [ -f "${sup_pidfile}" ] && [ "$(cat "${sup_pidfile}" 2>/dev/null)" = "$$" ]; then
    rm -f "${sup_pidfile}"
  fi
  pkill -f "${server}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Run the latest committed code. ff-only never overwrites local commits/edits.
if git -C "${project_dir}" pull --ff-only origin main >>"${log}" 2>&1; then
  log "git pull OK"
else
  log "git pull skipped/failed (non-fatal; serving current working tree)"
fi

signature() { md5sum "${project_dir}"/analysis/*.py 2>/dev/null | md5sum | awk '{print $1}'; }
pid=""
start() {
  python3 "${server}" --bind "${bind}" --port "${port}" >>"${log}" 2>&1 &
  pid=$!
  log "started dashboard_server (pid ${pid}) on ${bind}:${port}"
}

sig="$(signature)"
start
while true; do
  if ! kill -0 "${pid}" 2>/dev/null; then
    log "dashboard_server (pid ${pid}) exited; restarting"
    start
  fi
  new_sig="$(signature)"
  if [ "${new_sig}" != "${sig}" ]; then
    log "analysis source changed; reloading dashboard_server"
    sig="${new_sig}"
    kill "${pid}" 2>/dev/null || true
    wait "${pid}" 2>/dev/null || true
    start
  fi
  sleep 2
done
