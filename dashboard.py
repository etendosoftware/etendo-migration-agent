#!/usr/bin/env python3
"""
dashboard.py — Etendo Migration Dashboard

Reads all JSON migration reports from a directory and generates a
self-contained dashboard.html with aggregate stats, charts, and a
per-client HTML report viewer.

Usage:
    python3 dashboard.py --reports ./reports
    python3 dashboard.py --reports ./reports --output ./reports/dashboard.html
"""

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path


# ── Data loading ──────────────────────────────────────────────────────────────

def load_reports(reports_dir: str) -> list:
    results = []
    for json_path in sorted(Path(reports_dir).glob("*.json")):
        if json_path.stem == "dashboard":
            continue
        try:
            with open(json_path, encoding="utf-8") as f:
                report = json.load(f)
            if "migration_score" not in report:
                continue
            html_path = json_path.with_suffix(".html")
            report["_html_file"] = html_path.name if html_path.exists() else None
            report["_json_stem"] = json_path.stem
            results.append(report)
        except Exception:
            continue
    return results


# ── Aggregation ───────────────────────────────────────────────────────────────

def aggregate(records: list) -> dict:
    if not records:
        return {}

    scores = [r.get("migration_score") or 0 for r in records]
    avg_score = round(sum(scores) / len(scores), 1)

    migratable = sum(
        1 for r in records
        if (r.get("migration_score") or 0) >= 60
        and len(r.get("modules", {}).get("custom", [])) == 0
    )

    version_counter = Counter(
        r.get("platform", {}).get("version") or "—" for r in records
    )
    most_common_version = version_counter.most_common(1)[0][0]

    # Score distribution
    dist = {"easy": 0, "moderate": 0, "hard": 0, "very_hard": 0}
    for r in records:
        key = r.get("migratability") or "very_hard"
        dist[key] = dist.get(key, 0) + 1

    # Version distribution (sorted by version desc)
    version_items = sorted(version_counter.items(), key=lambda x: x[0], reverse=True)

    # Top 10 local_not_maintained modules by frequency
    nm_counter = Counter()
    for r in records:
        for mod in r.get("modules", {}).get("local_not_maintained", []):
            nm_counter[mod.get("java_package", "?")] += 1
    top10_nm = nm_counter.most_common(10)

    # Top 10 custom modules by LOC
    all_custom = []
    for r in records:
        cname = r.get("client", {}).get("name", "?")
        for mod in r.get("modules", {}).get("custom", []):
            all_custom.append({
                "label": mod.get("java_package", "?"),
                "loc": mod.get("line_count", 0),
                "client": cname,
            })
    all_custom.sort(key=lambda x: x["loc"], reverse=True)
    top10_custom = all_custom[:10]

    # Client rows
    clients = []
    for r in records:
        score = r.get("migration_score") or 0
        mods = r.get("modules", {})
        clients.append({
            "name": r.get("client", {}).get("name", r.get("_json_stem", "?")),
            "version": r.get("platform", {}).get("version") or "—",
            "score": score,
            "migratability": r.get("migratability") or "very_hard",
            "jar": len(mods.get("gradle_jar", [])),
            "source": len(mods.get("gradle_source", [])),
            "local_maintained": len(mods.get("local_maintained", [])),
            "not_maintained": len(mods.get("local_not_maintained", [])),
            "custom": len(mods.get("custom", [])),
            "html_file": r.get("_html_file"),
        })
    clients.sort(key=lambda x: x["score"], reverse=True)

    return {
        "kpis": {
            "total": len(records),
            "avg_score": avg_score,
            "migratable": migratable,
            "most_common_version": most_common_version,
        },
        "score_dist": {
            "labels": ["Fácil", "Moderada", "Difícil", "Muy difícil"],
            "values": [dist["easy"], dist["moderate"], dist["hard"], dist["very_hard"]],
            "colors": ["#22c55e", "#f59e0b", "#f97316", "#ef4444"],
        },
        "version_dist": {
            "labels": [v for v, _ in version_items],
            "values": [c for _, c in version_items],
        },
        "top_nm_modules": {
            "labels": [pkg for pkg, _ in top10_nm],
            "values": [cnt for _, cnt in top10_nm],
        },
        "top_custom_by_loc": {
            "labels": [m["label"] for m in top10_custom],
            "values": [m["loc"] for m in top10_custom],
            "clients": [m["client"] for m in top10_custom],
        },
        "clients": clients,
    }


# ── HTML rendering ────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0f172a;
    color: #f1f5f9;
    min-height: 100vh;
}
a { color: inherit; text-decoration: none; }

/* Header */
.header {
    background: #1e293b;
    border-bottom: 1px solid #334155;
    padding: 18px 32px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.header-logo { font-size: 1.5rem; }
.header h1 { font-size: 1.25rem; font-weight: 700; color: #f1f5f9; }
.header-sub { font-size: 0.8rem; color: #64748b; margin-left: auto; }

/* Layout */
.container { max-width: 1400px; margin: 0 auto; padding: 28px 24px; }

/* KPI Cards */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 28px;
}
.kpi-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px 24px;
}
.kpi-card .kpi-value {
    font-size: 2.2rem;
    font-weight: 800;
    line-height: 1;
    margin-bottom: 6px;
}
.kpi-card .kpi-label { font-size: 0.8rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; }
.kpi-card .kpi-icon { font-size: 1.4rem; margin-bottom: 10px; }

/* Charts */
.charts-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 16px;
}
.chart-full { margin-bottom: 16px; }
.chart-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px 24px;
}
.chart-card h2 {
    font-size: 0.85rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 16px;
}
.chart-wrap { position: relative; height: 220px; }
.chart-wrap-tall { position: relative; height: 280px; }
.chart-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #475569;
    font-size: 0.85rem;
}

/* Table */
.table-card {
    background: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
    overflow-x: auto;
}
.table-card h2 {
    font-size: 0.85rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 16px;
}
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th {
    text-align: left;
    padding: 8px 12px;
    color: #64748b;
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid #334155;
    cursor: default;
}
thead th.sortable { cursor: pointer; user-select: none; }
thead th.sortable:hover { color: #94a3b8; }
tbody tr { border-bottom: 1px solid #1e293b; transition: background 0.15s; }
tbody tr:hover { background: #253347; }
tbody td { padding: 10px 12px; vertical-align: middle; }
.td-name { font-weight: 600; }
.td-version { color: #94a3b8; font-family: monospace; font-size: 0.82rem; }
.td-num { text-align: right; }
.td-num-warn { text-align: right; color: #f97316; font-weight: 600; }
.td-num-purple { text-align: right; color: #a855f7; font-weight: 600; }

/* Badges */
.score-badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-weight: 700;
    font-size: 0.85rem;
    min-width: 42px;
    text-align: center;
}
.mig-badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
.mig-easy    { background: #14532d; color: #22c55e; }
.mig-mod     { background: #451a03; color: #f59e0b; }
.mig-hard    { background: #431407; color: #f97316; }
.mig-vhard   { background: #450a0a; color: #ef4444; }

/* Report button */
.btn-report {
    background: #0ea5e9;
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
}
.btn-report:hover { background: #0284c7; }
.btn-report:disabled { background: #334155; color: #475569; cursor: not-allowed; opacity: 0.5; }

/* Viewer panel */
.viewer-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.55);
    z-index: 90;
}
.viewer-backdrop.open { display: block; }
.viewer-panel {
    position: fixed;
    right: 0; top: 0;
    width: 62vw;
    height: 100vh;
    background: #1e293b;
    border-left: 1px solid #334155;
    box-shadow: -8px 0 40px rgba(0,0,0,0.6);
    z-index: 100;
    display: flex;
    flex-direction: column;
    transform: translateX(100%);
    transition: transform 0.3s ease;
}
.viewer-panel.open { transform: translateX(0); }
.viewer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 20px;
    border-bottom: 1px solid #334155;
    flex-shrink: 0;
}
.viewer-title { font-weight: 700; font-size: 0.95rem; }
.viewer-close {
    background: none;
    border: 1px solid #334155;
    color: #94a3b8;
    border-radius: 6px;
    padding: 4px 10px;
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
}
.viewer-close:hover { background: #334155; color: #f1f5f9; }
.viewer-frame { flex: 1; border: none; background: #fff; }

@media (max-width: 900px) {
    .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    .charts-row { grid-template-columns: 1fr; }
    .viewer-panel { width: 100vw; }
}
"""

_JS = """
const D = window.DASHBOARD_DATA;

// ── Score helpers ─────────────────────────────────────────────────────────
function scoreColor(s) {
    if (s >= 80) return '#22c55e';
    if (s >= 60) return '#f59e0b';
    if (s >= 40) return '#f97316';
    return '#ef4444';
}
function scoreBg(s) {
    if (s >= 80) return '#14532d';
    if (s >= 60) return '#451a03';
    if (s >= 40) return '#431407';
    return '#450a0a';
}
const MIG = {
    easy: ['mig-easy', 'Fácil'],
    moderate: ['mig-mod', 'Moderada'],
    hard: ['mig-hard', 'Difícil'],
    very_hard: ['mig-vhard', 'Muy difícil'],
};

// ── KPI cards ─────────────────────────────────────────────────────────────
function renderKpis() {
    const avg = D.kpis.avg_score;
    document.getElementById('kpi-total').textContent = D.kpis.total;
    const avgEl = document.getElementById('kpi-avg');
    avgEl.textContent = avg;
    avgEl.style.color = scoreColor(avg);
    document.getElementById('kpi-migratable').textContent = D.kpis.migratable;
    document.getElementById('kpi-version').textContent = D.kpis.most_common_version;
}

// ── Chart.js global defaults ──────────────────────────────────────────────
Chart.defaults.color = '#64748b';
Chart.defaults.borderColor = '#334155';

function truncLabel(str, max) {
    return str.length > max ? str.slice(0, max) + '…' : str;
}

// ── Score distribution (doughnut) ─────────────────────────────────────────
function renderScoreDist() {
    const ctx = document.getElementById('chart-score-dist').getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: D.score_dist.labels,
            datasets: [{
                data: D.score_dist.values,
                backgroundColor: D.score_dist.colors,
                borderWidth: 2,
                borderColor: '#1e293b',
            }]
        },
        options: {
            cutout: '60%',
            plugins: {
                legend: { position: 'bottom', labels: { color: '#94a3b8', padding: 12, font: { size: 12 } } }
            },
        }
    });
}

// ── Version distribution ──────────────────────────────────────────────────
function renderVersionDist() {
    const ctx = document.getElementById('chart-version-dist').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: D.version_dist.labels,
            datasets: [{
                data: D.version_dist.values,
                backgroundColor: '#0ea5e9',
                borderRadius: 4,
            }]
        },
        options: {
            indexAxis: 'y',
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { stepSize: 1, color: '#64748b' }, grid: { color: '#1e293b' } },
                y: { ticks: { color: '#94a3b8' }, grid: { display: false } }
            }
        }
    });
}

// ── Top local_not_maintained ──────────────────────────────────────────────
function renderNmModules() {
    const wrap = document.getElementById('chart-nm-wrap');
    if (!D.top_nm_modules.labels.length) {
        wrap.innerHTML = '<div class="chart-empty">Sin módulos sin mantenimiento</div>';
        return;
    }
    const ctx = document.getElementById('chart-nm').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: D.top_nm_modules.labels.map(l => truncLabel(l, 50)),
            datasets: [{
                data: D.top_nm_modules.values,
                backgroundColor: '#f97316',
                borderRadius: 4,
            }]
        },
        options: {
            indexAxis: 'y',
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { stepSize: 1, color: '#64748b' }, grid: { color: '#1e293b' } },
                y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } }
            }
        }
    });
}

// ── Top custom by LOC ─────────────────────────────────────────────────────
function renderCustomLoc() {
    const wrap = document.getElementById('chart-custom-wrap');
    if (!D.top_custom_by_loc.labels.length) {
        wrap.innerHTML = '<div class="chart-empty">Sin módulos de customización</div>';
        return;
    }
    const ctx = document.getElementById('chart-custom').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: D.top_custom_by_loc.labels.map(l => truncLabel(l, 45)),
            datasets: [{
                data: D.top_custom_by_loc.values,
                backgroundColor: '#a855f7',
                borderRadius: 4,
            }]
        },
        options: {
            indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => {
                            const client = D.top_custom_by_loc.clients[ctx.dataIndex];
                            return ` ${ctx.parsed.x.toLocaleString()} LOC — ${client}`;
                        }
                    }
                }
            },
            scales: {
                x: { ticks: { color: '#64748b' }, grid: { color: '#1e293b' } },
                y: { ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { display: false } }
            }
        }
    });
}

// ── Client table ──────────────────────────────────────────────────────────
let sortAsc = false;
let clientData = [...D.clients];

function renderTable() {
    const tbody = document.getElementById('clients-tbody');
    tbody.innerHTML = clientData.map(c => {
        const [migClass, migLabel] = MIG[c.migratability] || MIG['very_hard'];
        const nmClass = c.not_maintained > 0 ? 'td-num-warn' : 'td-num';
        const custClass = c.custom > 0 ? 'td-num-purple' : 'td-num';
        const btn = c.html_file
            ? `<button class="btn-report" onclick="openViewer('${c.html_file}', '${c.name.replace(/'/g,"\\'")}')">Ver reporte</button>`
            : `<button class="btn-report" disabled>Sin reporte</button>`;
        return `<tr>
            <td class="td-name">${c.name}</td>
            <td class="td-version">${c.version}</td>
            <td><span class="score-badge" style="background:${scoreBg(c.score)};color:${scoreColor(c.score)}">${c.score}</span></td>
            <td><span class="mig-badge ${migClass}">${migLabel}</span></td>
            <td class="td-num">${c.jar}</td>
            <td class="td-num">${c.source}</td>
            <td class="td-num">${c.local_maintained}</td>
            <td class="${nmClass}">${c.not_maintained}</td>
            <td class="${custClass}">${c.custom}</td>
            <td>${btn}</td>
        </tr>`;
    }).join('');
}

function toggleSort() {
    sortAsc = !sortAsc;
    clientData.sort((a, b) => sortAsc ? a.score - b.score : b.score - a.score);
    const icon = document.getElementById('sort-icon');
    if (icon) icon.textContent = sortAsc ? ' ↑' : ' ↓';
    renderTable();
}

// ── Viewer ────────────────────────────────────────────────────────────────
function openViewer(htmlFile, clientName) {
    document.getElementById('viewer-frame').src = htmlFile;
    document.getElementById('viewer-title').textContent = clientName;
    document.getElementById('viewer-panel').classList.add('open');
    document.getElementById('viewer-backdrop').classList.add('open');
}
function closeViewer() {
    document.getElementById('viewer-panel').classList.remove('open');
    document.getElementById('viewer-backdrop').classList.remove('open');
    setTimeout(() => { document.getElementById('viewer-frame').src = ''; }, 300);
}

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    renderKpis();
    renderScoreDist();
    renderVersionDist();
    renderNmModules();
    renderCustomLoc();
    renderTable();
});
"""


def render_html(data: dict, generated_at: str) -> str:
    data_json = json.dumps(data, ensure_ascii=False)
    avg = data.get("kpis", {}).get("avg_score", 0)

    def avg_color():
        if avg >= 80: return "#22c55e"
        if avg >= 60: return "#f59e0b"
        if avg >= 40: return "#f97316"
        return "#ef4444"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Etendo Migration Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>{_CSS}</style>
</head>
<body>

<div class="header">
  <span class="header-logo">📊</span>
  <h1>Etendo Migration Dashboard</h1>
  <span class="header-sub">Generado: {generated_at}</span>
</div>

<div class="container">

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-icon">🏢</div>
      <div class="kpi-value" style="color:#0ea5e9" id="kpi-total">—</div>
      <div class="kpi-label">Entornos analizados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon">🎯</div>
      <div class="kpi-value" style="color:{avg_color()}" id="kpi-avg">—</div>
      <div class="kpi-label">Score promedio</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon">✅</div>
      <div class="kpi-value" style="color:#22c55e" id="kpi-migratable">—</div>
      <div class="kpi-label">Potencialmente migrables</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-icon">📦</div>
      <div class="kpi-value" style="color:#a78bfa; font-size:1.4rem" id="kpi-version">—</div>
      <div class="kpi-label">Versión más frecuente</div>
    </div>
  </div>

  <!-- Charts row 1: Score dist + Version dist -->
  <div class="charts-row">
    <div class="chart-card">
      <h2>Distribución de migratabilidad</h2>
      <div class="chart-wrap">
        <canvas id="chart-score-dist"></canvas>
      </div>
    </div>
    <div class="chart-card">
      <h2>Versiones de Etendo instaladas</h2>
      <div class="chart-wrap">
        <canvas id="chart-version-dist"></canvas>
      </div>
    </div>
  </div>

  <!-- Chart: Top local_not_maintained -->
  <div class="chart-full">
    <div class="chart-card">
      <h2>Top módulos sin mantenimiento — frecuencia entre clientes</h2>
      <div class="chart-wrap-tall" id="chart-nm-wrap">
        <canvas id="chart-nm"></canvas>
      </div>
    </div>
  </div>

  <!-- Chart: Top custom by LOC -->
  <div class="chart-full">
    <div class="chart-card">
      <h2>Top customizaciones por volumen de código (LOC)</h2>
      <div class="chart-wrap-tall" id="chart-custom-wrap">
        <canvas id="chart-custom"></canvas>
      </div>
    </div>
  </div>

  <!-- Client table -->
  <div class="table-card">
    <h2>Detalle por cliente</h2>
    <table>
      <thead>
        <tr>
          <th>Cliente</th>
          <th>Versión</th>
          <th class="sortable" onclick="toggleSort()">Score<span id="sort-icon"> ↓</span></th>
          <th>Migratabilidad</th>
          <th class="td-num" title="Gradle JAR">JAR</th>
          <th class="td-num" title="Gradle Source">Source</th>
          <th class="td-num" title="Local Mantenido">Mant.</th>
          <th class="td-num" title="Local sin Mantenimiento" style="color:#f97316">Sin mant.</th>
          <th class="td-num" title="Customizaciones" style="color:#a855f7">Custom</th>
          <th>Reporte</th>
        </tr>
      </thead>
      <tbody id="clients-tbody"></tbody>
    </table>
  </div>

</div><!-- /container -->

<!-- Viewer -->
<div class="viewer-backdrop" id="viewer-backdrop" onclick="closeViewer()"></div>
<div class="viewer-panel" id="viewer-panel">
  <div class="viewer-header">
    <span class="viewer-title" id="viewer-title"></span>
    <button class="viewer-close" onclick="closeViewer()">✕ Cerrar</button>
  </div>
  <iframe class="viewer-frame" id="viewer-frame" src=""></iframe>
</div>

<script>window.DASHBOARD_DATA = {data_json};</script>
<script>{_JS}</script>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Etendo Migration Dashboard — aggregates JSON reports into a visual dashboard"
    )
    parser.add_argument(
        "--reports",
        default="./reports",
        help="Directory containing migration JSON + HTML reports (default: ./reports)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for dashboard.html (default: <reports>/dashboard.html)",
    )
    args = parser.parse_args()

    reports_dir = str(Path(args.reports).resolve())
    if not Path(reports_dir).is_dir():
        print(f"ERROR: '{reports_dir}' is not a directory")
        return

    output_path = Path(args.output) if args.output else Path(reports_dir) / "dashboard.html"

    records = load_reports(reports_dir)
    if not records:
        print(f"No migration reports found in: {reports_dir}")
        return

    data = aggregate(records)
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    html = render_html(data, generated_at)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Dashboard saved to: {output_path}")
    print(f"Clients: {data['kpis']['total']}  |  Avg score: {data['kpis']['avg_score']}  |  Migratable: {data['kpis']['migratable']}")


if __name__ == "__main__":
    main()
