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


ANALYSIS_OUTPUTS = (
    "validation.json",
    "batch_cell_summary.csv",
    "confirmatory_analysis.json",
)


def analysis_needs_refresh(result_dir: pathlib.Path) -> bool:
    """Refresh only when source evidence is newer than generated analysis."""
    analysis_dir = result_dir / "analysis"
    outputs = [analysis_dir / name for name in ANALYSIS_OUTPUTS]
    if any(not path.is_file() for path in outputs):
        return True
    sources = [result_dir / "config.snapshot.json", result_dir / "schedule.json"]
    sources.extend((result_dir / "raw").glob("*.jsonl"))
    existing_sources = [path for path in sources if path.is_file()]
    if not existing_sources:
        return False
    return max(path.stat().st_mtime_ns for path in existing_sources) > min(
        path.stat().st_mtime_ns for path in outputs
    )


def refresh_analysis(result_dir: pathlib.Path) -> str | None:
    """Regenerate analysis and return an error message without taking down the dashboard."""
    summarise = pathlib.Path(__file__).with_name("summarise.py")
    try:
        completed = subprocess.run(
            [sys.executable, str(summarise), str(result_dir)],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return "Analysis refresh exceeded 120 seconds; serving the last generated dashboard."
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        return f"Analysis refresh failed; serving the last generated dashboard. {detail}".strip()
    return None


def dashboard_data(result_dir: pathlib.Path) -> dict[str, Any]:
    analysis_dir = result_dir / "analysis"
    confirmatory = load_json(analysis_dir / "confirmatory_analysis.json", {})
    return {
        "run_name": result_dir.name,
        "validation": load_json(analysis_dir / "validation.json", {}),
        "summaries": load_csv(analysis_dir / "batch_cell_summary.csv"),
        "primary_deltas": load_csv(analysis_dir / "primary_batch_deltas.csv"),
        "confirmatory": confirmatory.get("contrasts", []),
        "primary_contrast": confirmatory.get("primary_contrast"),
        "pooled_tail": load_csv(analysis_dir / "pooled_tail_summary.csv"),
    }


def serialise_for_html(value: Any) -> str:
    return json.dumps(value, separators=(",", ":")).replace("<", "\\u003c")


DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PQC TLS benchmark — __TITLE__</title>
<style>
:root{--font:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;--bg:#f5f6f8;--surface:#ffffff;--surface2:#f8fafc;--text:#0f1722;--muted:#5b6573;--border:#e4e8ee;--accent:#2563eb;--ok:#0a7d3c;--okbg:#e7f6ec;--bad:#b42318;--badbg:#fbe9e8;--grid:rgba(15,23,42,.08);--shadow:0 1px 2px rgba(15,23,42,.04),0 6px 18px rgba(15,23,42,.05)}
@media (prefers-color-scheme: dark){:root{--bg:#0b0f17;--surface:#131a24;--surface2:#0f1620;--text:#e6edf3;--muted:#8b96a5;--border:#242d3a;--accent:#5b9aff;--ok:#3fd07a;--okbg:#10261a;--bad:#ff6b63;--badbg:#2a1413;--grid:rgba(255,255,255,.08);--shadow:0 1px 2px rgba(0,0,0,.3),0 8px 24px rgba(0,0,0,.25)}}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:15px;line-height:1.5;-webkit-font-smoothing:antialiased}
.mono{font-family:var(--mono);font-size:.92em}
header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--surface) 86%,transparent);backdrop-filter:saturate(140%) blur(10px);border-bottom:1px solid var(--border)}
header .row{max-width:1240px;margin:0 auto;padding:.85rem 1.5rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
.brand{display:flex;align-items:baseline;gap:.6rem;margin-right:auto}
.brand h1{font-size:1rem;margin:0;font-weight:650;letter-spacing:-.01em}
.brand .sub{color:var(--muted);font-size:.85rem;font-family:var(--mono)}
.badge{display:inline-flex;align-items:center;gap:.4rem;font-size:.78rem;font-weight:600;padding:.3rem .65rem;border-radius:999px;border:1px solid var(--border)}
.badge .dot{width:.5rem;height:.5rem;border-radius:50%}
.badge.ok{color:var(--ok);background:var(--okbg)} .badge.ok .dot{background:var(--ok)}
.badge.bad{color:var(--bad);background:var(--badbg)} .badge.bad .dot{background:var(--bad)}
.badge-detail{width:100%;color:var(--muted);font-size:.82rem}
main{max-width:1240px;margin:0 auto;padding:1.5rem 1.5rem 4rem}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.75rem;margin:1.25rem 0}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:.95rem 1.05rem;box-shadow:var(--shadow)}
.kpi .lbl{font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
.kpi .v{font-size:1.55rem;font-weight:700;font-variant-numeric:tabular-nums;margin-top:.2rem;letter-spacing:-.02em}
.hero{display:grid;grid-template-columns:1.5fr 1fr;gap:1rem;margin:1.25rem 0}
@media(max-width:780px){.hero{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow);padding:1.3rem 1.4rem}
.hero .eyebrow{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:600}
.hero .contrast{font-size:1.05rem;margin-top:.3rem}
.hero .cond{color:var(--muted);font-size:.9rem}
.hero .big{font-size:2.4rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em;margin-top:.5rem}
.hero .big .unit{font-size:1rem;font-weight:600;color:var(--muted);margin-left:.2rem}
.hero .stats{display:flex;flex-wrap:wrap;gap:1.1rem;margin-top:.5rem;font-size:.9rem;color:var(--muted)}
.hero .stats b{color:var(--text)}
.hero .verdict{margin-top:.4rem;font-size:.9rem;color:var(--muted)}
.toolbar{display:flex;flex-wrap:wrap;gap:.85rem;align-items:flex-end;background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);padding:.9rem 1rem;margin:1.5rem 0}
.toolbar label{display:flex;flex-direction:column;gap:.3rem;font-size:.7rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.toolbar select{min-width:9rem;padding:.5rem .7rem;font:inherit;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text)}
.toolbar button{padding:.55rem 1.05rem;font:inherit;font-weight:600;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text);cursor:pointer}
.toolbar button:hover{background:color-mix(in srgb,var(--accent) 14%,var(--surface2))}
.toolbar select:focus,.toolbar button:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.notice{padding:.8rem 1rem;border-radius:10px;font-size:.85rem;background:var(--badbg);color:var(--bad);margin:1rem 0}
section{margin-top:2rem}
section h2{font-size:1.05rem;margin:0 0 .2rem;font-weight:650;letter-spacing:-.01em}
section .desc{color:var(--muted);font-size:.84rem;margin:0 0 .9rem}
section .count{color:var(--muted);font-weight:400}
.charts-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(500px,1fr));gap:1.25rem}
@media(max-width:880px){.charts-grid{grid-template-columns:1fr}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:var(--shadow);overflow:hidden}
.panel .body{padding:1rem 1rem 1.1rem}
.chart-scroll{overflow-x:auto}
svg.chart{display:block;width:100%;height:auto;min-width:500px}
svg.chart .grid{stroke:var(--grid);stroke-width:1}
svg.chart .axis{stroke:var(--border);stroke-width:1}
svg.chart .tk{fill:var(--muted);font-size:11px;font-family:var(--font)}
svg.chart .ax{fill:var(--muted);font-size:11px;font-family:var(--font)}
.legend{display:flex;flex-wrap:wrap;gap:.9rem;padding:.6rem .1rem .1rem;font-size:.82rem;color:var(--muted)}
.legend .item{display:inline-flex;align-items:center;gap:.4rem}
.legend .sw{width:.85rem;height:.85rem;border-radius:3px}
table{width:100%;border-collapse:collapse;font-size:.85rem}
thead th{position:sticky;top:0;background:var(--surface2);text-align:left;font-size:.68rem;text-transform:uppercase;letter-spacing:.03em;color:var(--muted);font-weight:600;padding:.6rem .7rem;border-bottom:1px solid var(--border);white-space:nowrap}
tbody td{padding:.5rem .7rem;border-bottom:1px solid var(--border);font-variant-numeric:tabular-nums}
tbody tr:hover{background:var(--surface2)}
td.num,th.num{text-align:right}
.pill{display:inline-block;padding:.12rem .55rem;border-radius:999px;font-size:.7rem;font-weight:600}
.pill.sig{background:var(--okbg);color:var(--ok)}
.pill.nonsig{background:var(--surface2);color:var(--muted)}
.empty{padding:2.2rem 1rem;text-align:center;color:var(--muted);font-size:.9rem}
.inline-toggle{display:inline-flex;align-items:center;gap:.4rem;font-size:.82rem;color:var(--muted);cursor:pointer}
.inline-toggle input{accent-color:var(--accent)}
footer{color:var(--muted);font-size:.78rem;text-align:center;padding:2.5rem 1rem 0;line-height:1.6}
.run-select{display:flex;align-items:center;gap:.5rem}
.run-select label{display:flex;align-items:center;gap:.4rem;font-size:.78rem;color:var(--muted);font-weight:600}
.run-select select{padding:.35rem .6rem;font:inherit;font-size:.82rem;border:1px solid var(--border);border-radius:8px;background:var(--surface2);color:var(--text)}
.run-select select:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style>
</head>
<body>
<header>
  <div class="row">
    <div class="brand"><h1>PQC TLS benchmark dashboard</h1><span class="sub" id="run-name"></span></div>
    <div class="run-select" id="run-select" hidden><label>Run<select id="f-run" aria-label="Select benchmark run"></select></label></div>
    <span class="badge ok" id="badge"><span class="dot"></span>Validation passed</span>
    <div class="badge-detail" id="badge-detail"></div>
  </div>
</header>
<main>
  <div class="kpis">
    <div class="kpi"><div class="lbl">Observations</div><div class="v" id="k-obs">—</div></div>
    <div class="kpi"><div class="lbl">Batch cells</div><div class="v" id="k-cells">—</div></div>
    <div class="kpi"><div class="lbl">Successful handshakes</div><div class="v" id="k-succ">—</div></div>
    <div class="kpi"><div class="lbl">Success rate</div><div class="v" id="k-rate">—</div></div>
    <div class="kpi"><div class="lbl">Paired primary deltas</div><div class="v" id="k-deltas">—</div></div>
  </div>
  <div class="hero" id="hero-wrap">
    <div class="card" id="hero" hidden></div>
    <div class="card" id="hero-side">
      <div class="eyebrow">Reading guide</div>
      <ul class="desc reading-guide-list" style="margin:.4rem 0 0;padding-left:1.1rem;list-style:disc"><li><strong>Colour coding — </strong>one colour per key-exchange group, used consistently across all charts.</li><li style="margin-top:.5rem"><strong>Primary contrast — </strong>the pre-specified hybrid-vs-classical comparison at 50 ms RTT, 0% loss, with no multiplicity adjustment. Every other contrast shown is exploratory and Holm-adjusted.</li><li style="margin-top:.5rem"><strong>Tail percentiles under loss — </strong>batch-median order statistics; unstable at 0.5% loss. Read the shape, not the exact level.</li></ul>
    </div>
  </div>
  <div class="toolbar" role="group" aria-label="Dashboard filters">
    <label>Group<select id="f-group"></select></label>
    <label>RTT<select id="f-rtt"></select></label>
    <label>Loss per direction<select id="f-loss"></select></label>
    <button id="reset-filters" type="button">Reset filters</button>
  </div>
  <p class="notice" id="analysis-warning" hidden></p>
  <section>
    <h2>Handshake latency by group</h2>
    <p class="desc">Median, p95 and p99 handshake latency for the selected network condition, averaged over the matching batch cells.</p>
    <div class="panel"><div class="body"><div class="chart-scroll" id="chart-latency"></div></div></div>
  </section>
  <div class="charts-grid">
    <section>
      <h2>Median latency vs RTT</h2>
      <p class="desc">Median handshake latency against round-trip time for the selected loss level. Parallel, unit-slope lines indicate an RTT-dominated handshake; the vertical offset is the per-group compute cost.</p>
      <div class="panel"><div class="body"><div class="chart-scroll" id="chart-rtt"></div></div></div>
    </section>
    <section>
      <h2>Tail (p99) vs loss</h2>
      <p class="desc">99th-percentile latency against per-direction loss for the selected RTT. The steep rise is retransmission-driven and group-agnostic.</p>
      <div class="panel"><div class="body"><div class="chart-scroll" id="chart-tail"></div></div></div>
      <p class="desc" style="margin-top:.6rem"><label class="inline-toggle"><input type="checkbox" id="log-toggle"> Log y-axis (p99 spans roughly RTT to 4x RTT under loss)</label></p>
    </section>
  </div>
  <section>
    <h2>Pooled tail — block-bootstrap 95% CI <span class="count" id="tail-count"></span></h2>
    <p class="desc">Per-condition 95th and 99th percentiles pooled across all handshakes, with a block (cluster) bootstrap 95% CI for the p99 that resamples whole batches. These replace the unstable median-of-batch tail estimates shown elsewhere.</p>
    <div class="panel"><div class="body"><div class="chart-scroll"><table id="tail-table"><thead><tr><th>Group</th><th>RTT</th><th>Loss</th><th class="num">Handshakes</th><th class="num">Batches</th><th class="num">p95 (ms)</th><th class="num">p99 (ms)</th><th class="num">p99 95% CI (ms)</th></tr></thead><tbody></tbody></table></div></div></div>
  </section>
  <section>
    <h2>Condition summary <span class="count" id="summary-count"></span></h2>
    <p class="desc">Per-group, per-network-condition aggregates over the 20 batches.</p>
    <div class="panel"><div class="body"><div class="chart-scroll"><table id="summary-table"><thead><tr><th>Group</th><th>RTT</th><th>Loss</th><th class="num">Batches</th><th class="num">Median (ms)</th><th class="num">p95</th><th class="num">p99</th><th class="num">Failure rate</th><th class="num">Bytes read</th><th class="num">Bytes written</th></tr></thead><tbody></tbody></table></div></div></div>
  </section>
  <section id="contrast-section">
    <h2>Batch-aware contrast summary <span class="count" id="contrast-count"></span></h2>
    <p class="desc">Paired batch-level contrasts (comparison − baseline) with percentile-bootstrap 95% intervals and Holm-adjusted permutation p-values. Sig. denotes Holm p &lt; 0.05.</p>
    <div class="panel"><div class="body"><div class="chart-scroll"><table id="contrast-table"><thead><tr><th>Comparison</th><th>RTT</th><th>Loss</th><th class="num">Batches</th><th class="num">Mean Δ (ms)</th><th class="num">95% CI (ms)</th><th class="num">Holm p</th><th class="num">≤ 1 ms</th><th>Verdict</th></tr></thead><tbody></tbody></table></div></div></div>
  </section>
  <footer>PQC TLS benchmark dashboard. Tail percentiles under loss are batch-median estimates and are unstable at 0.5% loss; see the methodology limitations for details.</footer>
</main>
<script id="dashboard-data" type="application/json">__PAYLOAD__</script>
<script>
const data = JSON.parse(document.getElementById("dashboard-data").textContent);
const S = (data.summaries||[]).map(r => ({group:r.group, rtt:+r.rtt_ms, loss:+r.loss_percent_each_direction, failure_rate:+r.failure_rate, median:+r.median_latency_ms, p95:+r.p95_latency_ms, p99:+r.p99_latency_ms, br:+r.median_tls_bytes_read, bw:+r.median_tls_bytes_written}));
const C = data.confirmatory||[];
const P = data.primary_contrast||null;
const fmt = (v,d=2) => Number.isFinite(v) ? v.toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:(d>0&&Math.abs(v)<100?Math.min(d,2):0)}) : "—";
const fmtInt = v => Number.isFinite(v) ? v.toLocaleString() : "—";
const pct = v => Number.isFinite(v) ? (v*100).toLocaleString(undefined,{maximumFractionDigits:2})+"%" : "—";
const num = a => a.filter(x=>Number.isFinite(x));
const med = a => { const v=num(a); if(!v.length) return NaN; const s=[...v].sort((x,y)=>x-y); const m=s.length>>1; return s.length%2?s[m]:(s[m-1]+s[m])/2; };
const avg = a => { const v=num(a); return v.length?v.reduce((s,x)=>s+x,0)/v.length:NaN; };
const GROUPS = [...new Set(S.map(r=>r.group))].sort();
const RTTS = [...new Set(S.map(r=>r.rtt))].sort((a,b)=>a-b);
const LOSSES = [...new Set(S.map(r=>r.loss))].sort((a,b)=>a-b);
const COLOR = {X25519:"#0072B2", MLKEM768:"#D55E00", X25519MLKEM768:"#009E73"};
const colorOf = g => COLOR[g] || "#6b5bd8";
const cellMap = new Map();
S.forEach(r => { const k=r.group+"|"+r.rtt+"|"+r.loss; if(!cellMap.has(k)) cellMap.set(k,[]); cellMap.get(k).push(r); });
const cells = [...cellMap.values()].map(rs => { const f=rs[0]; return {group:f.group, rtt:f.rtt, loss:f.loss, n:rs.length, median:med(rs.map(r=>r.median)), p95:med(rs.map(r=>r.p95)), p99:med(rs.map(r=>r.p99)), fail:avg(rs.map(r=>r.failure_rate)), br:med(rs.map(r=>r.br)), bw:med(rs.map(r=>r.bw))}; });
const T = (data.pooled_tail||[]).map(t => ({group:t.group, rtt:+t.rtt_ms, loss:+t.loss_percent_each_direction, n:+t.n_handshakes, nb:+t.n_batches, p95:+t.pooled_p95_ms, p99:+t.pooled_p99_ms, lo99:+t.p99_block_ci95_low_ms, hi99:+t.p99_block_ci95_high_ms}));
let logScale=false;
const gf=document.getElementById("f-group"), rf=document.getElementById("f-rtt"), lf=document.getElementById("f-loss");
function fill(sel,vals,fm){sel.innerHTML=`<option value="">All</option>`+vals.map(v=>`<option value="${v}">${fm(v)}</option>`).join("");}
fill(gf,GROUPS,v=>v);
fill(rf,RTTS,v=>v+" ms");
fill(lf,LOSSES,v=>v+"%");
function pick(sel,pref){const opts=[...sel.options];sel.value=opts.some(o=>o.value===String(pref))?String(pref):(opts[1]?opts[1].value:"");}
function reset(){gf.value="";pick(rf,50);pick(lf,0);update();}
function visCells(){return cells.filter(c=>(!gf.value||c.group===gf.value)&&(!rf.value||c.rtt===+rf.value)&&(!lf.value||c.loss===+lf.value));}
function niceStep(range){const r=range||1;const exp=Math.floor(Math.log10(r));const f=r/Math.pow(10,exp);let nf=f<1.5?1:f<3?2:f<7?5:10;return nf*Math.pow(10,exp);}
function ticks(min,max,count){if(!Number.isFinite(min)||!Number.isFinite(max))return [];if(min===max){max=min+1;}const step=niceStep((max-min)/(count||6));const start=Math.floor(min/step)*step;const out=[];for(let v=start;v<=max+step*0.5;v+=step)out.push(+v.toFixed(10));return out;}
function lineChart(series,w,h,xLabel,yLabel){
  const m={l:56,r:20,t:18,b:48}; const pw=w-m.l-m.r, ph=h-m.t-m.b;
  const pts=[].concat(...series.map(s=>s.pts.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y))));
  if(!pts.length) return `<div class="empty">No data for the selected filters.</div>`;
  const xs=pts.map(p=>p.x), ys=pts.map(p=>p.y);
  let xmin=Math.min(...xs), xmax=Math.max(...xs), ymin=Math.min(...ys), ymax=Math.max(...ys);
  if(xmin===xmax){xmax=xmin+1;} ymin=Math.min(ymin,0);
  const pad=(ymax-ymin)*0.08||1; ymax+=pad;
  const xt=ticks(xmin,xmax,6), yt=ticks(ymin,ymax,6);
  const sx=v=>m.l+(v-xmin)/((xmax-xmin)||1)*pw;
  const sy=v=>m.t+ph-(v-ymin)/((ymax-ymin)||1)*ph;
  let g="";
  yt.forEach(v=>{const y=sy(v);g+=`<line class="grid" x1="${m.l}" y1="${y.toFixed(1)}" x2="${w-m.r}" y2="${y.toFixed(1)}"/><text class="tk" x="${m.l-8}" y="${(y+4).toFixed(1)}" text-anchor="end">${fmt(v,0)}</text>`;});
  xt.forEach(v=>{const x=sx(v);g+=`<line class="grid" x1="${x.toFixed(1)}" y1="${m.t}" x2="${x.toFixed(1)}" y2="${m.t+ph}" opacity="0.45"/><text class="tk" x="${x.toFixed(1)}" y="${(m.t+ph+18).toFixed(1)}" text-anchor="middle">${fmt(v,0)}</text>`;});
  g+=`<line class="axis" x1="${m.l}" y1="${(m.t+ph).toFixed(1)}" x2="${w-m.r}" y2="${(m.t+ph).toFixed(1)}"/>`;
  series.forEach((s,si)=>{const dash=[null,"8,5","2,4"][si%3];const sp=s.pts.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y));if(!sp.length)return;const d=sp.map(p=>`${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ");g+=`<polyline points="${d}" fill="none" stroke="${s.color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"${dash?` stroke-dasharray="${dash}"`:""}/>`;sp.forEach(p=>{g+=`<circle cx="${sx(p.x).toFixed(1)}" cy="${sy(p.y).toFixed(1)}" r="3.6" fill="var(--surface)" stroke="${s.color}" stroke-width="2"><title>${s.name} — ${fmt(p.x,0)} → ${fmt(p.y,2)} ms</title></circle>`;});});
  g+=`<text class="ax" x="${(m.l+pw/2).toFixed(1)}" y="${h-8}" text-anchor="middle">${xLabel}</text>`;
  g+=`<text class="ax" transform="rotate(-90 14 ${(m.t+ph/2).toFixed(1)})" x="14" y="${(m.t+ph/2).toFixed(1)}" text-anchor="middle">${yLabel}</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${yLabel} by ${xLabel}">${g}</svg>`;
}
function groupedBar(cats, series, w, h, yLabel){
  const m={l:56,r:20,t:18,b:54}; const pw=w-m.l-m.r, ph=h-m.t-m.b;
  const vals=[].concat(...series.map(s=>s.values.filter(Number.isFinite)));
  if(!cats.length||!vals.length) return `<div class="empty">No conditions match the selected filters.</div>`;
  let ymin=0, ymax=Math.max(...vals,1); const pad=(ymax-ymin)*0.08||1; ymax+=pad;
  const yt=ticks(ymin,ymax,6);
  const sy=v=>m.t+ph-(v-ymin)/((ymax-ymin)||1)*ph;
  let g="";
  yt.forEach(v=>{const y=sy(v);g+=`<line class="grid" x1="${m.l}" y1="${y.toFixed(1)}" x2="${w-m.r}" y2="${y.toFixed(1)}"/><text class="tk" x="${m.l-8}" y="${(y+4).toFixed(1)}" text-anchor="end">${fmt(v,0)}</text>`;});
  const slot=pw/cats.length, grpW=Math.min(slot*0.72,72), barW=(grpW/series.length)*0.86;
  cats.forEach((c,i)=>{const gx=m.l+slot*i+(slot-grpW)/2;
    series.forEach((s,j)=>{const val=s.values[i]; const vn=Number.isFinite(val)?val:0; const bh=(vn-ymin)/((ymax-ymin)||1)*ph; const x=gx+j*(grpW/series.length); const y=m.t+ph-bh;
      g+=`<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${Math.max(bh,0).toFixed(1)}" rx="2.5" fill="${s.color}"><title>${c.label} — ${s.name}: ${fmt(val,2)} ms</title></rect>`;
      if(Number.isFinite(val)) g+=`<text class="tk" x="${(x+barW/2).toFixed(1)}" y="${(y-5).toFixed(1)}" text-anchor="middle" font-size="10">${fmt(val,1)}</text>`;
    });
    g+=`<text class="tk" x="${(m.l+slot*i+slot/2).toFixed(1)}" y="${(m.t+ph+20).toFixed(1)}" text-anchor="middle">${c.label}</text>`;
  });
  g+=`<line class="axis" x1="${m.l}" y1="${(m.t+ph).toFixed(1)}" x2="${w-m.r}" y2="${(m.t+ph).toFixed(1)}"/>`;
  g+=`<text class="ax" transform="rotate(-90 14 ${(m.t+ph/2).toFixed(1)})" x="14" y="${(m.t+ph/2).toFixed(1)}" text-anchor="middle">${yLabel}</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${yLabel} by group">${g}</svg>`;
}
function legend(items){return `<div class="legend">${items.map(it=>`<span class="item"><span class="sw" style="background:${it.color}"></span>${it.name}</span>`).join("")}</div>`;}
function chartLatency(){
  const vis=visCells(); const groups=[...new Set(vis.map(c=>c.group))].sort();
  if(!groups.length) return `<div class="empty">No conditions match the selected filters.</div>`;
  const cats=groups.map(g=>({label:g}));
  const valFor=(g,fn)=>avg(vis.filter(c=>c.group===g).map(fn));
  const series=[{name:"Median",color:"#2563eb",values:groups.map(g=>valFor(g,c=>c.median))},{name:"p95",color:"#d97706",values:groups.map(g=>valFor(g,c=>c.p95))},{name:"p99",color:"#475569",values:groups.map(g=>valFor(g,c=>c.p99))}];
  return groupedBar(cats,series,760,360,"ms")+legend([{name:"Median",color:"#2563eb"},{name:"p95",color:"#d97706"},{name:"p99",color:"#475569"}]);
}
function chartVsRTT(){
  const loss=lf.value?+lf.value:null;
  const series=GROUPS.map(g=>{const pts=RTTS.map(rtt=>{const rs=cells.filter(c=>c.group===g&&c.rtt===rtt&&(loss===null||c.loss===loss));if(!rs.length)return null;return{x:rtt,y:avg(rs.map(c=>c.median))};}).filter(Boolean);return{name:g,color:colorOf(g),pts:pts};});
  return lineChart(series,760,360,"RTT (ms)","Median latency (ms)")+legend(GROUPS.map(g=>({name:g,color:colorOf(g)})));
}
function lineChartBands(series,w,h,xLabel,yLabel,logY){
  const m={l:56,r:20,t:18,b:48}; const pw=w-m.l-m.r, ph=h-m.t-m.b;
  const rows=[].concat(...series.map(s=>s.rows));
  const pts=rows.filter(r=>Number.isFinite(r.x)&&Number.isFinite(r.y));
  if(!pts.length) return `<div class="empty">No data for the selected filters.</div>`;
  const xs=pts.map(p=>p.x), ysAll=[].concat(...rows.flatMap(r=>[r.y,r.lo,r.hi].filter(Number.isFinite)));
  let xmin=Math.min(...xs), xmax=Math.max(...xs);
  let ymin=ysAll.length?Math.min(...ysAll):0, ymax=ysAll.length?Math.max(...ysAll):1;
  if(xmin===xmax){xmax=xmin+1;} ymin=Math.max(ymin,0);
  const pad=(ymax-ymin)*0.06||1; ymax+=pad; if(logY){ymin=Math.max(ymin,0.1);}
  let yticks = logY ? (()=>{const out=[];for(let e=Math.floor(Math.log10(ymin));e<=Math.ceil(Math.log10(ymax));e++){const v=Math.pow(10,e);if(v>=ymin*0.9&&v<=ymax*1.1)out.push(v);}return out;})() : ticks(ymin,ymax,6);
  const lyv=v=>logY?Math.log10(v):v;
  const lo=lyv(ymin), hi=lyv(ymax);
  const sx=v=>m.l+(v-xmin)/((xmax-xmin)||1)*pw;
  const sy=v=>m.t+ph-(lyv(v)-lo)/((hi-lo)||1)*ph;
  let g="";
  yticks.forEach(v=>{const y=sy(v);if(y<m.t-1||y>m.t+ph+1)return;g+=`<line class="grid" x1="${m.l}" y1="${y.toFixed(1)}" x2="${w-m.r}" y2="${y.toFixed(1)}"/><text class="tk" x="${m.l-8}" y="${(y+4).toFixed(1)}" text-anchor="end">${fmt(v,0)}</text>`;});
  const xsAll=[...new Set(pts.map(p=>p.x))].sort((a,b)=>a-b);
  xsAll.forEach(v=>{const x=sx(v);g+=`<line class="grid" x1="${x.toFixed(1)}" y1="${m.t}" x2="${x.toFixed(1)}" y2="${m.t+ph}" opacity="0.45"/><text class="tk" x="${x.toFixed(1)}" y="${(m.t+ph+18).toFixed(1)}" text-anchor="middle">${fmt(v,1)}</text>`;});
  g+=`<line class="axis" x1="${m.l}" y1="${(m.t+ph).toFixed(1)}" x2="${w-m.r}" y2="${(m.t+ph).toFixed(1)}"/>`;
  series.forEach(s=>{const sp=s.rows.filter(r=>Number.isFinite(r.x)&&Number.isFinite(r.y));if(!sp.length)return;
    if(sp.every(r=>Number.isFinite(r.lo)&&Number.isFinite(r.hi))){const top=sp.map(r=>`${sx(r.x).toFixed(1)},${sy(r.hi).toFixed(1)}`).join(" ");const bot=sp.slice().reverse().map(r=>`${sx(r.x).toFixed(1)},${sy(r.lo).toFixed(1)}`).join(" ");g+=`<polygon points="${top} ${bot}" fill="${s.color}" fill-opacity="0.13" stroke="none"><title>${s.name} 95% CI band</title></polygon>`;}
    const d=sp.map(r=>`${sx(r.x).toFixed(1)},${sy(r.y).toFixed(1)}`).join(" ");g+=`<polyline points="${d}" fill="none" stroke="${s.color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>`;
    sp.forEach(r=>{g+=`<circle cx="${sx(r.x).toFixed(1)}" cy="${sy(r.y).toFixed(1)}" r="3.6" fill="var(--surface)" stroke="${s.color}" stroke-width="2"><title>${s.name} — ${fmt(r.x,1)}% loss: ${fmt(r.y,2)} ms (95% CI ${fmt(r.lo,1)} to ${fmt(r.hi,1)})</title></circle>`;});});
  g+=`<text class="ax" x="${(m.l+pw/2).toFixed(1)}" y="${h-8}" text-anchor="middle">${xLabel}</text>`;
  g+=`<text class="ax" transform="rotate(-90 14 ${(m.t+ph/2).toFixed(1)})" x="14" y="${(m.t+ph/2).toFixed(1)}" text-anchor="middle">${yLabel}</text>`;
  return `<svg viewBox="0 0 ${w} ${h}" class="chart" role="img" aria-label="${yLabel} by ${xLabel}">${g}</svg>`;
}
function chartTail(){
  const rtt=rf.value?+rf.value:null;
  const series=GROUPS.map(g=>{const rows=T.filter(t=>t.group===g&&(rtt===null||t.rtt===rtt)).sort((a,b)=>a.loss-b.loss);return{name:g,color:colorOf(g),rows:rows.map(t=>({x:t.loss,y:t.p99,lo:t.lo99,hi:t.hi99}))};}).filter(s=>s.rows.length);
  return lineChartBands(series,760,360,"Loss per direction (%)","p99 latency (ms)",logScale)+legend(GROUPS.map(g=>({name:g,color:colorOf(g)})));
}
function updateTailTable(){
  const body=document.querySelector("#tail-table tbody"); if(!body) return; body.innerHTML="";
  const rows=T.slice().sort((a,b)=>a.rtt-b.rtt||a.loss-b.loss||a.group.localeCompare(b.group)).filter(t=>(!gf.value||t.group===gf.value)&&(!rf.value||t.rtt===+rf.value)&&(!lf.value||t.loss===+lf.value));
  rows.forEach(t=>{const ci=Number.isFinite(t.lo99)?`${fmt(t.lo99,1)} to ${fmt(t.hi99,1)}`:"—";const tr=document.createElement("tr");tr.innerHTML=`<td>${t.group}</td><td>${fmt(t.rtt,0)} ms</td><td>${fmt(t.loss,1)}%</td><td class="num">${fmtInt(t.n)}</td><td class="num">${t.nb}</td><td class="num">${fmt(t.p95,2)}</td><td class="num">${fmt(t.p99,2)}</td><td class="num">${ci}</td>`;body.appendChild(tr);});
  const tc=document.getElementById("tail-count"); if(tc) tc.textContent=rows.length?`(${rows.length})`:"";
}
function updateSummary(){
  const body=document.querySelector("#summary-table tbody"); body.innerHTML="";
  const rows=visCells().slice().sort((a,b)=>a.rtt-b.rtt||a.loss-b.loss||a.group.localeCompare(b.group));
  rows.forEach(r=>{const tr=document.createElement("tr"); tr.innerHTML=`<td>${r.group}</td><td>${fmt(r.rtt,0)} ms</td><td>${fmt(r.loss,1)}%</td><td class="num">${r.n}</td><td class="num">${fmt(r.median,3)}</td><td class="num">${fmt(r.p95,2)}</td><td class="num">${fmt(r.p99,2)}</td><td class="num">${pct(r.fail)}</td><td class="num">${fmtInt(r.br)}</td><td class="num">${fmtInt(r.bw)}</td>`; body.appendChild(tr);});
  const sc=document.getElementById("summary-count"); if(sc) sc.textContent=rows.length?`(${rows.length})`:"";
}
function filteredContrasts(){return C.filter(row=>(!gf.value||row.baseline_group===gf.value||row.comparison_group===gf.value)&&(!rf.value||+rf.value===row.rtt_ms)&&(!lf.value||+lf.value===row.loss_percent_each_direction));}
function accLe1(row){const t=(row.acceptance_threshold_sensitivity||[]).find(x=>x.threshold_ms===1.0);return t?t.proportion_at_or_below_threshold:NaN;}
function updateContrasts(){
  const body=document.querySelector("#contrast-table tbody"); body.innerHTML="";
  const rows=filteredContrasts().slice().sort((a,b)=>a.rtt_ms-b.rtt_ms||a.loss_percent_each_direction-b.loss_percent_each_direction||a.baseline_group.localeCompare(b.baseline_group)||a.comparison_group.localeCompare(b.comparison_group));
  rows.forEach(row=>{const sig=row.holm_adjusted_pvalue<0.05;const ci=Number.isFinite(row.ci95_low)?`${fmt(row.ci95_low,3)} – ${fmt(row.ci95_high,3)}`:"—";const tr=document.createElement("tr");tr.innerHTML=`<td class="mono">${row.comparison_group} − ${row.baseline_group}</td><td>${fmt(row.rtt_ms,0)} ms</td><td>${fmt(row.loss_percent_each_direction,1)}%</td><td class="num">${row.n}</td><td class="num">${fmt(row.mean,3)}</td><td class="num">${ci}</td><td class="num">${fmt(row.holm_adjusted_pvalue,4)}</td><td class="num">${pct(accLe1(row))}</td><td><span class="pill ${sig?"sig":"nonsig"}">${sig?"sig.":"n.s."}</span></td>`;body.appendChild(tr);});
  const cc=document.getElementById("contrast-count"); if(cc) cc.textContent=rows.length?`(${rows.length})`:"";
  const sec=document.getElementById("contrast-section"); if(sec) sec.hidden=!C.length;
}
function renderHero(){
  const host=document.getElementById("hero"); const wrap=document.getElementById("hero-wrap"); if(!host||!wrap) return;
  if(!P){host.hidden=true;wrap.style.gridTemplateColumns="1fr";return;}
  const match=C.find(r=>r.baseline_group===P.baseline_group&&r.comparison_group===P.comparison_group&&+r.rtt_ms===+P.rtt_ms&&+r.loss_percent_each_direction===+P.loss_percent_each_direction);
  const le1=match?accLe1(match):NaN;
  const ci=Number.isFinite(P.ci95_low)?`${fmt(P.ci95_low,3)} – ${fmt(P.ci95_high,3)} ms`:"—";
  const excludesZero=Number.isFinite(P.ci95_low)&&(P.ci95_low>0||P.ci95_high<0);
  const verdict=excludesZero?`Statistically significant (95% CI excludes 0). Below the 1 ms practical threshold for ${pct(le1)} of batches.`:`Not statistically significant at the pre-specified level.`;
  host.hidden=false; wrap.style.gridTemplateColumns="";
  host.innerHTML=`<div class="eyebrow">Primary contrast — pre-specified, no multiplicity adjustment</div><div class="contrast"><span class="mono">${P.comparison_group} − ${P.baseline_group}</span> <span class="cond">at ${fmt(P.rtt_ms,0)} ms RTT · ${fmt(P.loss_percent_each_direction,1)}% loss</span></div><div class="big">${fmt(P.mean,3)}<span class="unit">ms</span></div><div class="stats"><span>95% CI <b class="mono">${ci}</b></span><span>permutation p <b>${P.permutation_pvalue<0.0001?"&lt; 0.0001":fmt(P.permutation_pvalue,4)}</b></span><span>n = ${P.n} batches</span></div><div class="verdict">${verdict}</div>`;
}
function set(id,t){const e=document.getElementById(id); if(e) e.textContent=t;}
function renderKpis(){const v=data.validation||{};const succ=(v.status_counts||{}).success||0;const obs=v.observations||0;set("k-obs",fmtInt(obs));set("k-cells",fmtInt(v.batch_cells||0));set("k-succ",fmtInt(succ));set("k-rate",obs?pct(succ/obs):"—");set("k-deltas",fmtInt(v.primary_batch_deltas||0));}
function renderBadge(){const v=data.validation||{};const ok=v.valid===true;const b=document.getElementById("badge");if(b){b.className="badge "+(ok?"ok":"bad");b.innerHTML=`<span class="dot"></span>${ok?"Validation passed":"Validation needs attention"}`;}const d=document.getElementById("badge-detail");if(d)d.textContent=ok?"Frozen schedule, raw records and integrity checks are consistent.":((v.issues||[]).join("; ")||"unknown issue");const rn=document.getElementById("run-name");if(rn)rn.textContent=data.run_name;}
function renderWarn(){const w=document.getElementById("analysis-warning");if(w&&data.analysis_error){w.hidden=false;w.textContent=data.analysis_error;}}
function renderRunSelector(){
  const wrap=document.getElementById("run-select"), sel=document.getElementById("f-run");
  const runs=data.available_runs;
  if(!wrap||!sel||!Array.isArray(runs)||runs.length<2){ if(wrap) wrap.hidden=true; return; }
  wrap.hidden=false;
  sel.innerHTML="";
  runs.forEach(name=>{const opt=document.createElement("option");opt.value=name;opt.textContent=name;if(name===data.run_name)opt.selected=true;sel.appendChild(opt);});
  sel.addEventListener("change",()=>{location.href="/dashboard.html?run="+encodeURIComponent(sel.value);});
}
function update(){renderHero();renderKpis();updateSummary();updateTailTable();document.getElementById("chart-latency").innerHTML=chartLatency();document.getElementById("chart-rtt").innerHTML=chartVsRTT();document.getElementById("chart-tail").innerHTML=chartTail();updateContrasts();}
[gf,rf,lf].forEach(c=>c.addEventListener("change",update));
document.getElementById("reset-filters").addEventListener("click",reset);
const logT=document.getElementById("log-toggle"); if(logT) logT.addEventListener("change",()=>{logScale=logT.checked;document.getElementById("chart-tail").innerHTML=chartTail();});
renderBadge();renderWarn();renderRunSelector();reset();
</script>
</body>
</html>"""


def render_dashboard(data: dict[str, Any]) -> str:
    title = html.escape(str(data["run_name"]))
    payload = serialise_for_html(data)
    return DASHBOARD_TEMPLATE.replace("__TITLE__", title).replace("__PAYLOAD__", payload)


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
