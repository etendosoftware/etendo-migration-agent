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
            if html_path.exists():
                report["_html_file"] = html_path.name
            else:
                # fallback: look for a file named after the client
                client_name = report.get("client", {}).get("name", "")
                if client_name:
                    safe = client_name.replace(" ", "-").replace("/", "-")
                    alt = json_path.parent / f"{safe}.html"
                    report["_html_file"] = alt.name if alt.exists() else None
                else:
                    report["_html_file"] = None
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

    # Version range: min, max and normalized average position
    def _ver_num(v):
        try:
            parts = [int(x) for x in str(v).split(".")]
            return parts[0] * 10000 + (parts[1] if len(parts) > 1 else 0) * 100 + (parts[2] if len(parts) > 2 else 0)
        except Exception:
            return 0

    valid_versions = [r.get("platform", {}).get("version") for r in records if r.get("platform", {}).get("version")]
    if valid_versions:
        sorted_versions = sorted(valid_versions, key=_ver_num)
        min_version = sorted_versions[0]
        max_version = sorted_versions[-1]
        min_num = _ver_num(min_version)
        max_num = _ver_num(max_version)
        avg_num = sum(_ver_num(v) for v in valid_versions) / len(valid_versions)
        version_avg_pct = round((avg_num - min_num) / (max_num - min_num) * 100, 1) if max_num != min_num else 50.0
    else:
        min_version = max_version = "—"
        version_avg_pct = 50.0

    # Platform breakdown (Etendo vs Openbravo)
    platform_counter = Counter(
        r.get("platform", {}).get("type", "etendo") for r in records
    )
    count_etendo = platform_counter.get("etendo", 0)
    count_openbravo = platform_counter.get("openbravo", 0)

    # Score distribution
    dist = {"easy": 0, "moderate": 0, "hard": 0, "very_hard": 0}
    for r in records:
        key = r.get("migratability") or "very_hard"
        dist[key] = dist.get(key, 0) + 1

    # Version distribution grouped by major
    from collections import defaultdict
    major_groups = defaultdict(list)
    for version, count in version_counter.items():
        major = version.split(".")[0] if version != "—" else "—"
        major_groups[major].append({"version": version, "count": count})

    def _major_sort_key(m):
        try:
            return int(m)
        except Exception:
            return -1

    version_grouped = []
    for major in sorted(major_groups.keys(), key=_major_sort_key, reverse=True):
        versions = sorted(major_groups[major], key=lambda x: x["version"], reverse=True)
        version_grouped.append({
            "major": major,
            "total": sum(v["count"] for v in versions),
            "versions": versions,
        })

    # Version distribution (sorted by version desc) — kept for legacy
    version_items = sorted(version_counter.items(), key=lambda x: x[0], reverse=True)

    # Top 50 local_not_maintained modules by frequency (translations flagged)
    import re as _re
    _LOCALE_RE = _re.compile(r'[._][a-z]{2}[._][a-zA-Z]{2}$')
    nm_counter = Counter()
    for r in records:
        for mod in r.get("modules", {}).get("local_not_maintained", []):
            nm_counter[mod.get("java_package", "?")] += 1
    top10_nm = nm_counter.most_common(50)
    nm_translations = {pkg for pkg, _ in top10_nm if _LOCALE_RE.search(pkg)}

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
        core = r.get("core_divergences", {})
        client_version = r.get("platform", {}).get("version") or "—"
        base_version = core.get("base_version") or "—"
        baseline_type = core.get("baseline_type") or "zip"
        baseline_exact = baseline_type == "expanded" or base_version == client_version
        clients.append({
            "name": r.get("client", {}).get("name", r.get("_json_stem", "?")),
            "version": client_version,
            "score": score,
            "migratability": r.get("migratability") or "very_hard",
            "jar": len(mods.get("gradle_jar", [])),
            "source": len(mods.get("gradle_source", [])),
            "local_maintained": len(mods.get("local_maintained", [])),
            "not_maintained": len(mods.get("local_not_maintained", [])),
            "custom": len(mods.get("custom", [])),
            "html_file": r.get("_html_file"),
            "base_version": base_version,
            "baseline_exact": baseline_exact,
        })
    clients.sort(key=lambda x: x["score"], reverse=True)

    return {
        "kpis": {
            "total": len(records),
            "avg_score": avg_score,
            "migratable": migratable,
            "min_version": min_version,
            "max_version": max_version,
            "version_avg_pct": version_avg_pct,
            "etendo": count_etendo,
            "openbravo": count_openbravo,
        },
        "score_dist": {
            "labels": ["Fácil", "Moderada", "Difícil", "Muy difícil"],
            "values": [dist["easy"], dist["moderate"], dist["hard"], dist["very_hard"]],
            "colors": ["#86efac", "#fde68a", "#fed7aa", "#fca5a5"],
        },
        "version_dist": {
            "labels": [v for v, _ in version_items],
            "values": [c for _, c in version_items],
        },
        "version_dist_grouped": version_grouped,
        "top_nm_modules": {
            "labels": [pkg for pkg, _ in top10_nm],
            "values": [cnt for _, cnt in top10_nm],
            "is_translation": [pkg in nm_translations for pkg, _ in top10_nm],
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
    background: #f8fafc;
    color: #1e293b;
    min-height: 100vh;
}
a { color: inherit; text-decoration: none; }

/* Header */
.header {
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
    padding: 16px 32px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.header h1 { font-size: 1.1rem; font-weight: 600; color: #0f172a; }
.header-sub { font-size: 0.78rem; color: #94a3b8; margin-left: auto; }

/* Layout */
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }

/* KPI Cards */
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 20px;
}
.kpi-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 18px 20px;
}
.kpi-card .kpi-value {
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 5px;
}
.kpi-card .kpi-label {
    font-size: 0.75rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}

/* Platform split inside KPI card */
.platform-split { display: flex; gap: 20px; margin-top: 6px; }
.platform-split span { font-size: 0.85rem; font-weight: 600; color: #475569; }
.platform-split strong { color: #1e293b; }

/* Version range indicator */
.ver-range-labels {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    font-weight: 600;
    color: #64748b;
    margin-bottom: 8px;
}
.ver-range-track {
    position: relative;
    height: 4px;
    background: #e2e8f0;
    border-radius: 99px;
    margin-bottom: 4px;
}
.ver-range-fill {
    position: absolute;
    left: 0; top: 0; bottom: 0;
    background: #cbd5e1;
    border-radius: 99px;
    width: 100%;
}
.ver-range-marker {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 12px;
    height: 12px;
    background: #3b82f6;
    border: 2px solid #fff;
    border-radius: 50%;
    box-shadow: 0 1px 3px rgba(59,130,246,0.4);
}
.ver-range-marker::before {
    content: '▲';
    position: absolute;
    bottom: -16px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 8px;
    color: #3b82f6;
    line-height: 1;
}
.ver-avg-label {
    text-align: center;
    font-size: 0.7rem;
    color: #3b82f6;
    font-weight: 600;
    margin-top: 14px;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}

/* Charts */
.charts-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 12px;
}
.chart-full { margin-bottom: 12px; }
.chart-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 20px 24px;
}
.chart-card h2 {
    font-size: 0.72rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 18px;
}
.chart-wrap { position: relative; height: 220px; }
.chart-wrap-tall { position: relative; height: 260px; }
.chart-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #cbd5e1;
    font-size: 0.82rem;
}

/* Table */
.table-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 12px;
    overflow-x: auto;
}
.table-card h2 {
    font-size: 0.72rem;
    font-weight: 600;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 16px;
}
table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
thead th {
    text-align: left;
    padding: 6px 12px;
    color: #cbd5e1;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    border-bottom: 1px solid #f1f5f9;
    cursor: default;
}
thead th.sortable { cursor: pointer; user-select: none; }
thead th.sortable:hover { color: #94a3b8; }
tbody tr { border-bottom: 1px solid #f8fafc; transition: background 0.1s; }
tbody tr:hover { background: #f8fafc; }
tbody td { padding: 10px 12px; vertical-align: middle; color: #334155; }
.td-name { font-weight: 600; color: #0f172a; }
.td-version { color: #94a3b8; font-family: monospace; font-size: 0.8rem; }
.td-num { text-align: right; color: #64748b; }
.td-num-warn { text-align: right; color: #ea580c; font-weight: 600; }
.td-num-purple { text-align: right; color: #7c3aed; font-weight: 600; }

/* Badges */
.score-badge {
    display: inline-block;
    padding: 2px 9px;
    border-radius: 99px;
    font-weight: 700;
    font-size: 0.82rem;
    min-width: 38px;
    text-align: center;
}
.mig-badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}
.mig-easy    { background: #f0fdf4; color: #16a34a; }
.mig-mod     { background: #fefce8; color: #ca8a04; }
.mig-hard    { background: #fff7ed; color: #ea580c; }
.mig-vhard   { background: #fef2f2; color: #dc2626; }

/* Report button */
.btn-report {
    background: none;
    color: #3b82f6;
    border: 1px solid #bfdbfe;
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 0.75rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
}
.btn-report:hover { background: #eff6ff; border-color: #93c5fd; }
.btn-report:disabled { color: #cbd5e1; border-color: #e2e8f0; cursor: not-allowed; }

/* Viewer panel */
.viewer-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15,23,42,0.25);
    z-index: 90;
}
.viewer-backdrop.open { display: block; }
.viewer-panel {
    position: fixed;
    right: 0; top: 0;
    width: 62vw;
    height: 100vh;
    background: #ffffff;
    border-left: 1px solid #e2e8f0;
    box-shadow: -4px 0 24px rgba(0,0,0,0.07);
    z-index: 100;
    display: flex;
    flex-direction: column;
    transform: translateX(100%);
    transition: transform 0.25s ease;
}
.viewer-panel.open { transform: translateX(0); }
.viewer-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 20px;
    border-bottom: 1px solid #f1f5f9;
    flex-shrink: 0;
}
.viewer-title { font-weight: 600; font-size: 0.9rem; color: #0f172a; }
.viewer-close {
    background: none;
    border: 1px solid #e2e8f0;
    color: #94a3b8;
    border-radius: 5px;
    padding: 3px 10px;
    cursor: pointer;
    font-size: 0.8rem;
    transition: all 0.15s;
}
.viewer-close:hover { background: #f1f5f9; color: #475569; }
.viewer-frame { flex: 1; border: none; background: #fff; }

/* Baseline badges */
.baseline-badge {
    font-family: monospace;
    font-size: 0.78rem;
    padding: 2px 7px;
    border-radius: 4px;
    font-weight: 600;
    white-space: nowrap;
}
.baseline-exact {
    background: #f0fdf4;
    color: #16a34a;
}
.baseline-approx {
    background: #fff7ed;
    color: #c2410c;
}

/* Version grouped tree */
.ver-group { border-bottom: 1px solid #f1f5f9; }
.ver-group:last-child { border-bottom: none; }
.ver-group-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 4px;
    cursor: pointer;
    user-select: none;
    transition: background 0.1s;
    border-radius: 6px;
}
.ver-group-header:hover { background: #f8fafc; }
.ver-major {
    font-size: 0.9rem;
    font-weight: 700;
    color: #0f172a;
    font-family: monospace;
    min-width: 32px;
}
.ver-count-badge {
    font-size: 0.72rem;
    font-weight: 600;
    color: #0284c7;
    background: #e0f2fe;
    padding: 1px 8px;
    border-radius: 99px;
}
.ver-toggle {
    margin-left: auto;
    font-size: 0.65rem;
    color: #94a3b8;
    transition: transform 0.2s;
}
.ver-group-body { padding: 0 4px 8px 16px; }
.ver-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 5px 8px;
    border-radius: 5px;
    transition: background 0.1s;
}
.ver-item:hover { background: #f8fafc; }
.ver-version {
    font-family: monospace;
    font-size: 0.82rem;
    color: #475569;
}
.ver-item-count {
    font-size: 0.75rem;
    font-weight: 600;
    color: #64748b;
    background: #f1f5f9;
    padding: 1px 7px;
    border-radius: 99px;
    min-width: 24px;
    text-align: center;
}

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
    if (s >= 80) return '#15803d';
    if (s >= 60) return '#a16207';
    if (s >= 40) return '#c2410c';
    return '#b91c1c';
}
function scoreBg(s) {
    if (s >= 80) return '#dcfce7';
    if (s >= 60) return '#fef9c3';
    if (s >= 40) return '#ffedd5';
    return '#fee2e2';
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
    document.getElementById('kpi-ver-min').textContent = D.kpis.min_version;
    document.getElementById('kpi-ver-max').textContent = D.kpis.max_version;
    document.getElementById('kpi-ver-marker').style.left = D.kpis.version_avg_pct + '%';
    document.getElementById('kpi-etendo-count').textContent = D.kpis.etendo;
    document.getElementById('kpi-openbravo-count').textContent = D.kpis.openbravo;
}

// ── Chart.js global defaults ──────────────────────────────────────────────
Chart.defaults.color = '#94a3b8';
Chart.defaults.borderColor = '#f1f5f9';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

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
                borderWidth: 0,
                hoverOffset: 4,
            }]
        },
        options: {
            cutout: '68%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#64748b',
                        padding: 16,
                        font: { size: 11 },
                        boxWidth: 10,
                        boxHeight: 10,
                        usePointStyle: true,
                        pointStyle: 'circle',
                    }
                }
            },
        }
    });
}

// ── Version distribution (grouped tree) ──────────────────────────────────
function renderVersionDist() {
    const container = document.getElementById('version-dist-container');
    const groups = D.version_dist_grouped;
    if (!groups || !groups.length) {
        container.innerHTML = '<div class="chart-empty">Sin datos</div>';
        return;
    }
    container.innerHTML = groups.map((group, i) => `
        <div class="ver-group">
            <div class="ver-group-header" onclick="toggleVerGroup(${i})">
                <span class="ver-major">v${group.major}</span>
                <span class="ver-count-badge">${group.total} entorno${group.total !== 1 ? 's' : ''}</span>
                <span class="ver-toggle" id="ver-toggle-${i}">▶</span>
            </div>
            <div class="ver-group-body" id="ver-group-body-${i}" style="display:none">
                ${group.versions.map(v => `
                    <div class="ver-item">
                        <span class="ver-version">${v.version}</span>
                        <span class="ver-item-count">${v.count}</span>
                    </div>
                `).join('')}
            </div>
        </div>
    `).join('');
}

function toggleVerGroup(i) {
    const body = document.getElementById('ver-group-body-' + i);
    const toggle = document.getElementById('ver-toggle-' + i);
    const isOpen = body.style.display !== 'none';
    body.style.display = isOpen ? 'none' : 'block';
    toggle.textContent = isOpen ? '▶' : '▼';
}

// ── Top local_not_maintained ──────────────────────────────────────────────
function renderNmModules() {
    const wrap = document.getElementById('chart-nm-wrap');
    if (!D.top_nm_modules.labels.length) {
        wrap.innerHTML = '<div class="chart-empty">Sin módulos sin mantenimiento</div>';
        return;
    }
    const colors = D.top_nm_modules.is_translation.map(t => t ? '#94a3b8' : '#f97316');
    const ctx = document.getElementById('chart-nm').getContext('2d');
    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: D.top_nm_modules.labels.map(l => truncLabel(l, 50)),
            datasets: [{
                data: D.top_nm_modules.values,
                backgroundColor: colors,
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
                            const isTrans = D.top_nm_modules.is_translation[ctx.dataIndex];
                            return ` ${ctx.parsed.x} cliente${ctx.parsed.x !== 1 ? 's' : ''}${isTrans ? ' — traducción' : ''}`;
                        }
                    }
                }
            },
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
        const baseLabel = c.baseline_exact
            ? `<span class="baseline-badge baseline-exact" title="Baseline exacto">${c.base_version}</span>`
            : `<span class="baseline-badge baseline-approx" title="Baseline aproximado (ZIP estático)">${c.base_version} ⚠</span>`;
        return `<tr>
            <td class="td-name">${c.name}</td>
            <td class="td-version">${c.version}</td>
            <td>${baseLabel}</td>
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
  <h1>Etendo Migration Dashboard</h1>
  <span class="header-sub">Generado: {generated_at}</span>
</div>

<div class="container">

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label" style="margin-bottom:8px">Entornos</div>
      <div class="kpi-value" style="color:#0284c7" id="kpi-total">—</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label" style="margin-bottom:8px">Score promedio</div>
      <div class="kpi-value" style="color:{avg_color()}" id="kpi-avg">—</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label" style="margin-bottom:8px">Migrables</div>
      <div class="kpi-value" style="color:#16a34a" id="kpi-migratable">—</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label" style="margin-bottom:12px">Rango de versiones</div>
      <div class="ver-range-labels">
        <span class="ver-min" id="kpi-ver-min">—</span>
        <span class="ver-max" id="kpi-ver-max">—</span>
      </div>
      <div class="ver-range-track">
        <div class="ver-range-marker" id="kpi-ver-marker" style="left:50%"></div>
      </div>
      <div class="ver-avg-label">promedio</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label" style="margin-bottom:12px">Plataforma</div>
      <div class="platform-split">
        <span>Etendo <strong id="kpi-etendo-count">—</strong></span>
        <span>Openbravo <strong id="kpi-openbravo-count">—</strong></span>
      </div>
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
      <div id="version-dist-container"></div>
    </div>
  </div>

  <!-- Chart: Top local_not_maintained -->
  <div class="chart-full">
    <div class="chart-card">
      <h2>Top 50 módulos sin mantenimiento — frecuencia entre clientes</h2>
      <div style="position:relative;height:900px;" id="chart-nm-wrap">
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
          <th>Base comparación</th>
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
