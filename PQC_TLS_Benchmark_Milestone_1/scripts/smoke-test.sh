#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
smoke_dir="${project_dir}/results/smoke-test-$(date -u +%Y%m%dT%H%M%SZ)"

cleanup() {
  "${project_dir}/scripts/lab-down.sh" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "${project_dir}"
make test
scripts/check-environment.py
scripts/lab-up.sh
scripts/run-experiment.py --max-cells 1 --output "${smoke_dir}"
analysis/summarise.py "${smoke_dir}"

test -s "${smoke_dir}/analysis/batch_cell_summary.csv"
test -s "${smoke_dir}/analysis/validation.json"
echo "Smoke test passed: ${smoke_dir}"

