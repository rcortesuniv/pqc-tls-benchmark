#!/usr/bin/env python3
"""Generate a self-contained interactive dashboard for one benchmark run."""
from __future__ import annotations

import argparse
import csv
import html
import json
import pathlib
import subprocess
import sys
from typing import Any


def load_json(path: pathlib.Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def load_csv(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def refresh_analysis(result_dir: pathlib.Path) -> None:
    summarise = pathlib.Path(__file__).with_name("summarise.py")
    subprocess.run([sys.executable, str(summarise), str(result_dir)], check=False, capture_output=True, text=True)


def dashboard_data(result_dir: pathlib.Path) -> dict[str, Any]:
    analysis_dir = result_dir / "analysis"
    return {
        "run_name": result_dir.name,
        "validation": load_json(analysis_dir / "validation.json", {}),
        "summaries": load_csv(analysis_dir / "batch_cell_summary.csv"),
        "primary_deltas": load_csv(analysis_dir / "primary_batch_deltas.csv"),
        "confirmatory": load_json(analysis_dir / "confirmatory_analysis.json", {}).get("contrasts", []),
    }


def serialise_for_html(value: Any) -> str:
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")


def render_dashboard(data: dict[str, Any]) -> str:
    title = html.escape(str(data["run_name"]))
    payload = serialise_for_html(data)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PQC TLS benchmark — {title}</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: Canvas; color: CanvasText; }}
main {{ max-width: 1280px; margin: auto; padding: 2rem; }}
h1 {{ margin-bottom: .25rem; }}
.muted {{ color: GrayText; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1rem; margin: 1.25rem 0; }}
.card {{ border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: .5rem; padding: 1rem; }}
.value {{ font-size: 1.7rem; font-weight: 650; }}
.ok {{ color: #147a3d; }} .bad {{ color: #b42318; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: end; margin: 1.5rem 0; }}
label {{ display: grid; gap: .3rem; font-weight: 600; }}
select {{ min-width: 12rem; padding: .4rem; }}
section {{ margin-top: 2rem; }}
.chart-wrap {{ overflow-x: auto; border: 1px solid color-mix(in srgb, CanvasText 15%, transparent); border-radius: .5rem; padding: .5rem; }}
svg {{ display: block; min-width: 760px; width: 100%; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border-bottom: 1px solid color-mix(in srgb, CanvasText 15%, transparent); padding: .55rem; text-align: left; }}
th {{ white-space: nowrap; }}
.number {{ text-align: right; font-variant-numeric: tabular-nums; }}
.notice {{ padding: .75rem 1rem; border-left: .3rem solid currentColor; background: color-mix(in srgb, CanvasText 6%, transparent); }}
</style>
</head>
<body>
<main>
  <h1>PQC TLS benchmark dashboard</h1>
  <p class="muted" id="run-name"></p>
  <div id="validation" class="notice" role="status"></div>
  <div class="grid" aria-label="Run summary">
    <div class="card"><div class="muted">Observations</div><div class="value" id="observations">—</div></div>
    <div class="card"><div class="muted">Batch cells</div><div class="value" id="batch-cells">—</div></div>
    <div class="card"><div class="muted">Successful handshakes</div><div class="value" id="successes">—</div></div>
    <div class="card"><div class="muted">Paired hybrid deltas</div><div class="value" id="paired-deltas">—</div></div>
  </div>
  <div class="controls" aria-label="Dashboard filters">
    <label>Group <select id="group-filter"></select></label>
    <label>RTT <select id="rtt-filter"></select></label>
    <label>Loss per direction <select id="loss-filter"></select></label>
  </div>
  <section>
    <h2>Median handshake latency</h2>
    <p class="muted">Each bar is the mean of available batch-cell medians for one selected condition.</p>
    <div class="chart-wrap"><svg id="latency-chart" viewBox="0 0 980 390" role="img" aria-label="Median handshake latency by group and network condition"></svg></div>
  </section>
  <section>
    <h2>Filtered condition summary</h2>
    <div class="chart-wrap"><table id="summary-table"><thead><tr><th>Group</th><th>RTT</th><th>Loss</th><th class="number">Batches</th><th class="number">Median latency (ms)</th><th class="number">Failure rate</th><th class="number">Bytes read</th><th class="number">Bytes written</th></tr></thead><tbody></tbody></table></div>
  </section>
  <section id="confirmatory-section">
    <h2>Batch-aware contrast summary</h2>
    <p class="muted">These contrasts are generated only where both groups occur in the same batch and network condition.</p>
    <div class="chart-wrap"><table id="contrast-table"><thead><tr><th>Comparison</th><th>RTT</th><th>Loss</th><th class="number">Batches</th><th class="number">Mean delta (ms)</th><th class="number">95% interval (ms)</th><th class="number">Holm-adjusted p</th></tr></thead><tbody></tbody></table></div>
  </section>
</main>
<script id="dashboard-data" type="application/json">{payload}</script>
<script>
const data = JSON.parse(document.getElementById('dashboard-data').textContent);
const summaries = data.summaries.map(row => ({{...row, rtt_ms:+row.rtt_ms, loss_percent_each_direction:+row.loss_percent_each_direction, attempts:+row.attempts, successes:+row.successes, failure_rate:+row.failure_rate, median_latency_ms:+row.median_latency_ms, median_tls_bytes_read:+row.median_tls_bytes_read, median_tls_bytes_written:+row.median_tls_bytes_written}}));
const fmt = (value, digits=2) => Number.isFinite(value) ? value.toLocaleString(undefined, {{maximumFractionDigits:digits}}) : '—';
const median = values => {{ const sorted=[...values].sort((a,b)=>a-b); const middle=Math.floor(sorted.length/2); return sorted.length%2 ? sorted[middle] : (sorted[middle-1]+sorted[middle])/2; }};
const aggregate = rows => {{
  const map = new Map();
  rows.forEach(row => {{
    const key = [row.group,row.rtt_ms,row.loss_percent_each_direction].join('|');
    if (!map.has(key)) map.set(key, []); map.get(key).push(row);
  }});
  return [...map.values()].map(rows => {{
    const first=rows[0];
    return {{...first, batches:rows.length, median_latency_ms:rows.reduce((sum,row)=>sum+row.median_latency_ms,0)/rows.length, failure_rate:rows.reduce((sum,row)=>sum+row.failure_rate,0)/rows.length, median_tls_bytes_read:median(rows.map(row=>row.median_tls_bytes_read)), median_tls_bytes_written:median(rows.map(row=>row.median_tls_bytes_written))}};
  }}).sort((a,b)=>a.rtt_ms-b.rtt_ms || a.loss_percent_each_direction-b.loss_percent_each_direction || a.group.localeCompare(b.group));
}};
function fill(select, values, label) {{ select.innerHTML = `<option value="">All ${{label}}</option>` + values.map(value => `<option value="${{value}}">${{value}}</option>`).join(''); }}
const groupFilter=document.getElementById('group-filter'), rttFilter=document.getElementById('rtt-filter'), lossFilter=document.getElementById('loss-filter');
fill(groupFilter,[...new Set(summaries.map(row=>row.group))].sort(),'groups');
fill(rttFilter,[...new Set(summaries.map(row=>row.rtt_ms))].sort((a,b)=>a-b).map(value=>`${{value}} ms`),'RTT levels');
fill(lossFilter,[...new Set(summaries.map(row=>row.loss_percent_each_direction))].sort((a,b)=>a-b).map(value=>`${{value}}%`),'loss levels');
function filtered() {{ return summaries.filter(row => (!groupFilter.value || row.group===groupFilter.value) && (!rttFilter.value || `${{row.rtt_ms}} ms`===rttFilter.value) && (!lossFilter.value || `${{row.loss_percent_each_direction}}%`===lossFilter.value)); }}
function updateSummary(rows) {{
  const body=document.querySelector('#summary-table tbody'); body.innerHTML='';
  aggregate(rows).forEach(row => {{ const tr=document.createElement('tr'); tr.innerHTML=`<td>${{row.group}}</td><td>${{row.rtt_ms}} ms</td><td>${{row.loss_percent_each_direction}}%</td><td class="number">${{row.batches}}</td><td class="number">${{fmt(row.median_latency_ms,3)}}</td><td class="number">${{fmt(row.failure_rate*100,2)}}%</td><td class="number">${{fmt(row.median_tls_bytes_read,0)}}</td><td class="number">${{fmt(row.median_tls_bytes_written,0)}}</td>`; body.appendChild(tr); }});
}}
function updateChart(rows) {{
  const values=aggregate(rows), svg=document.getElementById('latency-chart');
  const width=980, height=390, left=62, bottom=72, top=24, right=22, plotHeight=height-top-bottom, plotWidth=width-left-right;
  const max=Math.max(1,...values.map(row=>row.median_latency_ms));
  const ticks=[0,.25,.5,.75,1].map(fraction=>fraction*max);
  let marks=`<title>Median handshake latency</title><desc>Filtered median handshake latency by group and network condition.</desc>`;
  ticks.forEach(value => {{ const y=top+plotHeight-(value/max)*plotHeight; marks+=`<line x1="${{left}}" y1="${{y}}" x2="${{width-right}}" y2="${{y}}" stroke="currentColor" opacity=".15"/><text x="${{left-8}}" y="${{y+4}}" text-anchor="end" font-size="12">${{fmt(value,0)}}</text>`; }});
  const slot=plotWidth/Math.max(values.length,1), barWidth=Math.min(42,slot*.65);
  values.forEach((row,index) => {{ const barHeight=(row.median_latency_ms/max)*plotHeight, x=left+slot*index+(slot-barWidth)/2, y=top+plotHeight-barHeight, label=`${{row.group}} · ${{row.rtt_ms}} ms · ${{row.loss_percent_each_direction}}%`; marks+=`<rect x="${{x}}" y="${{y}}" width="${{barWidth}}" height="${{barHeight}}" fill="#2878b5"><title>${{label}}: ${{fmt(row.median_latency_ms,3)}} ms</title></rect><text x="${{x+barWidth/2}}" y="${{y-6}}" text-anchor="middle" font-size="11">${{fmt(row.median_latency_ms,1)}}</text><text x="${{x+barWidth/2}}" y="${{height-16}}" text-anchor="end" transform="rotate(-45 ${{x+barWidth/2}} ${{height-16}})" font-size="11">${{label}}</text>`; }});
  marks+=`<line x1="${{left}}" y1="${{top+plotHeight}}" x2="${{width-right}}" y2="${{top+plotHeight}}" stroke="currentColor"/><text x="14" y="18" font-size="12">ms</text>`; svg.innerHTML=marks;
}}
function update() {{ const rows=filtered(); updateSummary(rows); updateChart(rows); }}
[groupFilter,rttFilter,lossFilter].forEach(control=>control.addEventListener('change',update));
document.getElementById('run-name').textContent=data.run_name;
const validation=data.validation, valid=validation.valid===true; const notice=document.getElementById('validation'); notice.textContent=valid ? 'Validation passed: the frozen schedule, raw records and integrity checks are consistent.' : `Validation requires attention: ${{(validation.issues||[]).join('; ')||'unknown issue'}}`; notice.className=`notice ${{valid?'ok':'bad'}}`;
document.getElementById('observations').textContent=fmt(validation.observations||0,0); document.getElementById('batch-cells').textContent=fmt(validation.batch_cells||0,0); document.getElementById('successes').textContent=fmt((validation.status_counts||{{}}).success||0,0); document.getElementById('paired-deltas').textContent=fmt(validation.primary_batch_deltas||0,0);
const contrastBody=document.querySelector('#contrast-table tbody');
(data.confirmatory||[]).forEach(row => {{ const tr=document.createElement('tr'); const interval=row.ci95_low===null ? '—' : `${{fmt(row.ci95_low,3)}} to ${{fmt(row.ci95_high,3)}}`; tr.innerHTML=`<td>${{row.comparison_group}} − ${{row.baseline_group}}</td><td>${{row.rtt_ms}} ms</td><td>${{row.loss_percent_each_direction}}%</td><td class="number">${{row.n}}</td><td class="number">${{fmt(row.mean,3)}}</td><td class="number">${{interval}}</td><td class="number">${{fmt(row.holm_adjusted_pvalue,4)}}</td>`; contrastBody.appendChild(tr); }});
if (!(data.confirmatory||[]).length) document.getElementById('confirmatory-section').hidden=true;
update();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--no-refresh", action="store_true", help="Use existing analysis files without regenerating them")
    args = parser.parse_args()
    if not args.result_dir.is_dir():
        parser.error("result_dir must be an existing result directory")
    if not args.no_refresh:
        refresh_analysis(args.result_dir)
    output = args.output or args.result_dir / "analysis" / "dashboard.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_dashboard(dashboard_data(args.result_dir)), encoding="utf-8")
    print(f"Dashboard written to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
