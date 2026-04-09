#!/usr/bin/env python3
"""
portfolio_analysis.py — Cross-client portfolio analysis.

Scans reports/*.json for clients with custom_assessment and/or ui_readiness,
produces three strategic sections and injects them into reports/dashboard.html.
Also saves reports/portfolio_analysis.json.

Usage:
    python3 scripts/portfolio_analysis.py
"""

import json
import re
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).parent.parent))
from analyzer.ui_scorer import enrich_ui_readiness

RISK_W = {"high": 3, "medium": 2, "low": 1}
_LOCALE_RE = re.compile(r'[._][a-z]{2}[._][a-zA-Z]{2}$')


# ── Step 1: Discover analyzed reports ─────────────────────────────────────────

def discover_reports(reports_dir: Path) -> list:
    analyzed = []
    for path in sorted(reports_dir.glob("*.json")):
        if path.stem in ("ranking", "portfolio_analysis"):
            continue
        try:
            r = json.loads(path.read_text())
        except Exception:
            continue
        has_ui = "ui_readiness" in r and r["ui_readiness"].get("features")
        has_ca = "custom_assessment" in r and (
            r["custom_assessment"].get("core_customizations") or
            r["custom_assessment"].get("custom_modules") or
            r["custom_assessment"].get("unmaintained_modules")
        )
        if has_ui or has_ca:
            analyzed.append({
                "slug": path.stem,
                "name": r.get("client", {}).get("name", path.stem),
                "platform": r.get("platform", {}),
                "migration_score": r.get("migration_score"),
                "migratability": r.get("migratability"),
                "ui_readiness": r.get("ui_readiness") if has_ui else None,
                "custom_assessment": r.get("custom_assessment") if has_ca else None,
            })
    return analyzed


# ── Step 2: UI feature-first roadmap analysis ─────────────────────────────────
# Instead of ranking clients, we aggregate PER FEATURE across all clients.
# For each feature: how many clients have it as critica / alta / media / no_aplica?
# Portfolio priority = weighted sum (critica×4, alta×2, media×1).
# This directly drives the roadmap: features affecting many clients with high priority
# should be implemented first in the new UI.

PRIORITY_WEIGHT = {"critica": 4, "alta": 2, "media": 1, "no_aplica": 0}


def build_ui_feature_roadmap(analyzed: list) -> tuple:
    """
    Returns (feature_roadmap, ui_clients_meta).

    feature_roadmap: list of dicts, one per unique feature section, sorted by
        portfolio_score desc — ready to render as roadmap table.

    ui_clients_meta: list of (slug, name, ui_score) for a compact summary block.
    """
    # Map section → aggregated data
    feature_map: dict = {}

    ui_clients_meta = []

    for a in analyzed:
        if not a["ui_readiness"]:
            continue
        ui = a["ui_readiness"]
        if ui.get("ui_migration_score") is None:
            enrich_ui_readiness(ui)

        ui_clients_meta.append({
            "slug": a["slug"],
            "name": a["name"],
            "ui_score": ui.get("ui_migration_score", 0),
            "global_status": ui.get("global_status", ""),
        })

        for f in ui.get("features", []):
            section = f.get("section", "")
            if not section:
                continue
            if section not in feature_map:
                feature_map[section] = {
                    "section": section,
                    "title": f.get("title", section),
                    "status": f.get("status", ""),
                    "completion_pct": f.get("completion_pct", 0),
                    "clients_by_priority": {"critica": [], "alta": [], "media": [], "no_aplica": []},
                    "ad_counts": [],
                }
            entry = feature_map[section]
            priority = f.get("priority", "no_aplica")
            entry["clients_by_priority"].setdefault(priority, []).append(a["name"])
            if f.get("ad_count"):
                entry["ad_counts"].append(f["ad_count"])
            # Keep the worst (lowest) completion_pct seen across clients
            if f.get("completion_pct", 0) < entry["completion_pct"] or entry["completion_pct"] == 0:
                entry["completion_pct"] = f.get("completion_pct", 0)
            # Keep status from first client that has it (same feature = same UI status)
            if not entry["status"] and f.get("status"):
                entry["status"] = f.get("status", "")

    # Compute portfolio_score and total_clients_affected for each feature
    feature_roadmap = []
    for section, data in feature_map.items():
        cbp = data["clients_by_priority"]
        portfolio_score = sum(
            PRIORITY_WEIGHT.get(p, 0) * len(clients)
            for p, clients in cbp.items()
        )
        affected = sum(len(c) for p, c in cbp.items() if p != "no_aplica")
        avg_ad = round(sum(data["ad_counts"]) / len(data["ad_counts"])) if data["ad_counts"] else 0
        feature_roadmap.append({
            "section": section,
            "title": data["title"],
            "status": data["status"],
            "completion_pct": data["completion_pct"],
            "clients_critica": cbp.get("critica", []),
            "clients_alta": cbp.get("alta", []),
            "clients_media": cbp.get("media", []),
            "clients_no_aplica": cbp.get("no_aplica", []),
            "total_affected": affected,
            "avg_ad_count": avg_ad,
            "portfolio_score": portfolio_score,
        })

    # Sort: highest portfolio_score first, then completion_pct asc (least done = most urgent)
    feature_roadmap.sort(key=lambda x: (-x["portfolio_score"], x["completion_pct"]))

    return feature_roadmap, ui_clients_meta


# ── Step 3: Unmaintained module analysis ───────────────────────────────────────

def build_module_candidates(analyzed: list) -> tuple:
    module_map = {}

    for a in analyzed:
        if not a["custom_assessment"]:
            continue
        for m in a["custom_assessment"].get("unmaintained_modules", []):
            pkg = m.get("java_package", "")
            base_pkg = _LOCALE_RE.sub("", pkg)
            if base_pkg not in module_map:
                module_map[base_pkg] = {
                    "clients": [], "risk_levels": [], "has_replacement": None,
                    "official_replacement_name": None, "generalization": None,
                    "effort_update_hours_avg": [], "effort_saas_hours_avg": [],
                    "name": "", "function": "", "api_changes": set(),
                }
            entry = module_map[base_pkg]
            if a["slug"] not in entry["clients"]:
                entry["clients"].append(a["slug"])
            if m.get("risk"):
                entry["risk_levels"].append(m["risk"])
            if m.get("has_official_replacement") is not None:
                entry["has_replacement"] = m["has_official_replacement"]
            if m.get("official_replacement_name"):
                entry["official_replacement_name"] = m["official_replacement_name"]
            if m.get("generalization"):
                entry["generalization"] = m["generalization"]
            if m.get("effort_update_hours"):
                entry["effort_update_hours_avg"].append(m["effort_update_hours"])
            if m.get("effort_saas_hours"):
                entry["effort_saas_hours_avg"].append(m["effort_saas_hours"])
            if m.get("name") and not entry["name"]:
                entry["name"] = m["name"]
            if m.get("function") and not entry["function"]:
                entry["function"] = m["function"]
            for api in m.get("api_changes_applicable", []):
                entry["api_changes"].add(api)

    module_candidates = []
    for pkg, data in module_map.items():
        if not data["clients"]:
            continue
        max_risk = max(data["risk_levels"], key=lambda r: RISK_W.get(r, 0)) if data["risk_levels"] else "low"
        priority_score = len(data["clients"]) * RISK_W.get(max_risk, 1)
        avg_update = round(sum(data["effort_update_hours_avg"]) / len(data["effort_update_hours_avg"])) if data["effort_update_hours_avg"] else 0
        avg_saas = round(sum(data["effort_saas_hours_avg"]) / len(data["effort_saas_hours_avg"])) if data["effort_saas_hours_avg"] else 0
        module_candidates.append({
            "java_package": pkg,
            "name": data["name"],
            "function": data["function"],
            "clients": data["clients"],
            "client_count": len(data["clients"]),
            "max_risk": max_risk,
            "has_replacement": data["has_replacement"],
            "official_replacement_name": data["official_replacement_name"],
            "generalization": data["generalization"],
            "api_changes": sorted(data["api_changes"]),
            "avg_effort_update_hours": avg_update,
            "avg_effort_saas_hours": avg_saas,
            "priority_score": priority_score,
        })

    module_candidates.sort(key=lambda x: (-x["priority_score"], -x["client_count"], x["java_package"]))
    etendo_candidates = [
        m for m in module_candidates
        if m["client_count"] >= 2 or (m["max_risk"] == "high" and not m["has_replacement"])
    ]
    replaceable = [m for m in module_candidates if m not in etendo_candidates and m["has_replacement"]]
    return etendo_candidates, replaceable


# ── Step 4: Generalizable customizations ───────────────────────────────────────

def build_generalizable(analyzed: list, etendo_candidates: list) -> list:
    generalizable = []
    for a in analyzed:
        if not a["custom_assessment"]:
            continue
        client_name = a["name"]
        for c in a["custom_assessment"].get("core_customizations", []):
            if c.get("conclusion") == "upstream":
                generalizable.append({
                    "type": "core",
                    "client": client_name,
                    "name": c.get("name", ""),
                    "description": c.get("description", ""),
                    "justification": c.get("justification", ""),
                    "effort_saas_hours": c.get("effort_saas_hours", 0),
                })
        for m in a["custom_assessment"].get("custom_modules", []):
            if m.get("generalization") == "bundle_candidate":
                generalizable.append({
                    "type": "module",
                    "client": client_name,
                    "name": m.get("name", ""),
                    "java_package": m.get("java_package", ""),
                    "description": m.get("description", ""),
                    "complexity": m.get("complexity", ""),
                    "effort_saas_hours": m.get("effort_saas_hours", 0),
                    "recommendation": m.get("recommendation", ""),
                })
        for m in a["custom_assessment"].get("unmaintained_modules", []):
            if m.get("generalization") == "bundle_candidate" and not m.get("has_official_replacement"):
                base_pkg = _LOCALE_RE.sub("", m.get("java_package", ""))
                if not any(e["java_package"] == base_pkg for e in etendo_candidates):
                    generalizable.append({
                        "type": "module_unmaintained",
                        "client": client_name,
                        "name": m.get("name", ""),
                        "java_package": m.get("java_package", ""),
                        "description": m.get("function", ""),
                        "risk": m.get("risk", ""),
                        "effort_saas_hours": m.get("effort_saas_hours", 0),
                        "recommendation": m.get("recommendation", ""),
                    })
    return generalizable


# ── Step 5: Save portfolio_analysis.json ───────────────────────────────────────

def save_portfolio_json(reports_dir: Path, analyzed, feature_roadmap, ui_clients_meta, etendo_candidates, generalizable):
    portfolio = {
        "generated": date.today().isoformat(),
        "analyzed_clients": [a["slug"] for a in analyzed],
        "ui_feature_roadmap": [
            {
                "section": f["section"],
                "title": f["title"],
                "status": f["status"],
                "completion_pct": f["completion_pct"],
                "portfolio_score": f["portfolio_score"],
                "clients_critica": f["clients_critica"],
                "clients_alta": f["clients_alta"],
                "clients_media": f["clients_media"],
                "total_affected": f["total_affected"],
                "avg_ad_count": f["avg_ad_count"],
            }
            for f in feature_roadmap
        ],
        "ui_clients_meta": ui_clients_meta,
        "module_maintenance_candidates": etendo_candidates,
        "generalizable_customizations": generalizable,
    }
    (reports_dir / "portfolio_analysis.json").write_text(
        json.dumps(portfolio, indent=2, ensure_ascii=False)
    )


# ── Step 6: Build HTML and inject into dashboard ───────────────────────────────

def _ui_score_badge(score):
    if score is None:
        return '<span style="color:#aaa">—</span>'
    if score >= 80:
        color, bg = "#16a34a", "#dcfce7"
    elif score >= 60:
        color, bg = "#ca8a04", "#fef9c3"
    elif score >= 40:
        color, bg = "#ea580c", "#ffedd5"
    else:
        color, bg = "#dc2626", "#fee2e2"
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            f'background:{bg};color:{color};font-weight:700;font-size:13px">{score}</span>')


def _status_badge(status):
    MAP = {
        "blocked": ("#dc2626", "#fee2e2", "Bloqueado"),
        "partial":  ("#ea580c", "#ffedd5", "Parcial"),
        "ready":    ("#16a34a", "#dcfce7", "Listo"),
    }
    color, bg, label = MAP.get(status, ("#6b7280", "#f3f4f6", status))
    return (f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
            f'background:{bg};color:{color};font-size:12px;font-weight:600">{label}</span>')


def _risk_badge(risk):
    MAP = {
        "high":   ("#dc2626", "#fee2e2", "Alto"),
        "medium": ("#ca8a04", "#fef9c3", "Medio"),
        "low":    ("#16a34a", "#dcfce7", "Bajo"),
    }
    c, bg, label = MAP.get(risk, ("#6b7280", "#f3f4f6", risk))
    return (f'<span style="display:inline-block;padding:1px 7px;border-radius:9px;'
            f'background:{bg};color:{c};font-size:11px;font-weight:600">{label}</span>')


def _client_pills(client_names: list, color: str, bg: str) -> str:
    if not client_names:
        return ""
    pills = "".join(
        f'<span style="display:inline-block;padding:1px 7px;border-radius:9px;'
        f'background:{bg};color:{color};font-size:11px;margin:1px">{n}</span>'
        for n in client_names
    )
    return f'<div style="line-height:1.8">{pills}</div>'


def _roadmap_priority_badge(score: int, n_critica: int) -> str:
    """Translate portfolio_score into a roadmap priority label."""
    if n_critica >= 2:
        return '<span style="background:#dc2626;color:#fff;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700">P1 — Inmediata</span>'
    if n_critica == 1 and score >= 4:
        return '<span style="background:#ea580c;color:#fff;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700">P2 — Alta</span>'
    if score >= 4:
        return '<span style="background:#ca8a04;color:#fff;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700">P3 — Media</span>'
    if score >= 1:
        return '<span style="background:#6b7280;color:#fff;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700">P4 — Baja</span>'
    return '<span style="background:#e5e7eb;color:#9ca3af;padding:2px 10px;border-radius:10px;font-size:11px">Sin impacto</span>'


def _completion_bar(pct: int) -> str:
    color = "#16a34a" if pct >= 80 else "#ca8a04" if pct >= 50 else "#dc2626"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="flex:1;height:6px;background:#f3f4f6;border-radius:3px">'
        f'<div style="width:{pct}%;height:6px;background:{color};border-radius:3px"></div>'
        f'</div>'
        f'<span style="font-size:11px;color:#6b7280;white-space:nowrap">{pct}%</span>'
        f'</div>'
    )


def build_ui_section(feature_roadmap: list, ui_clients_meta: list) -> str:
    all_blocked = sum(1 for c in ui_clients_meta if c["global_status"] == "blocked")
    n_clients = len(ui_clients_meta)
    avg_score = round(sum(c["ui_score"] for c in ui_clients_meta) / n_clients) if n_clients else 0

    # Compact per-client score summary
    client_badges = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;'
        f'padding:4px 10px;margin:3px;font-size:12px">'
        f'<b>{c["name"]}</b>&nbsp;{_ui_score_badge(c["ui_score"])}</span>'
        for c in sorted(ui_clients_meta, key=lambda x: x["ui_score"], reverse=True)
    )

    rows = ""
    for f in feature_roadmap:
        n_crit = len(f["clients_critica"])
        n_alta = len(f["clients_alta"])
        n_media = len(f["clients_media"])
        total = f["total_affected"]

        if total == 0:
            continue  # skip features no client uses

        rows += (
            f'<tr>'
            f'<td>'
            f'  <div style="font-weight:600;font-size:13px">{f["title"]}</div>'
            f'  <div style="font-size:10px;color:#9ca3af;margin-top:1px">§ {f["section"]}'
            f'  · Estado UI: <b>{f["status"] or "—"}</b></div>'
            f'</td>'
            f'<td style="text-align:center">{_roadmap_priority_badge(f["portfolio_score"], n_crit)}</td>'
            f'<td style="text-align:center;font-size:12px">'
            f'  <span style="color:#dc2626;font-weight:700">{n_crit}</span>'
            f'  <span style="color:#ea580c;font-weight:700"> · {n_alta}</span>'
            f'  <span style="color:#ca8a04;font-weight:700"> · {n_media}</span>'
            f'  <span style="color:#6b7280;font-size:10px"> / {n_clients}</span>'
            f'</td>'
            f'<td>'
            f'  {_client_pills(f["clients_critica"], "#dc2626", "#fee2e2")}'
            f'  {_client_pills(f["clients_alta"], "#ea580c", "#ffedd5")}'
            f'  {_client_pills(f["clients_media"], "#ca8a04", "#fef9c3")}'
            f'</td>'
            f'<td>{_completion_bar(f["completion_pct"])}</td>'
            f'<td style="text-align:center;font-size:12px;color:#6b7280">'
            f'  {f["avg_ad_count"] if f["avg_ad_count"] else "—"}'
            f'</td>'
            f'</tr>'
        )

    return f"""
<div class="portfolio-section" id="portfolio-ui">
  <h2>Preparación para nueva UI — Roadmap por funcionalidad</h2>
  <p class="portfolio-lead">
    La tabla prioriza las funcionalidades pendientes de la nueva UI de Etendo según su <b>impacto real en el portfolio</b>:
    una funcionalidad crítica para 3 clientes es más urgente que una crítica para 1.
    <b>Prioridad de roadmap</b>: P1 = crítica en ≥2 entornos · P2 = crítica en 1 entorno con impacto alto ·
    P3 = alta en varios · P4 = baja relevancia general.
    Scores por entorno: {client_badges}
    <br><span style="color:#6b7280;font-size:12px">
    {n_clients} entornos analizados · {all_blocked} bloqueados · score promedio {avg_score}/100
    </span>
  </p>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Funcionalidad</th>
        <th style="text-align:center;width:130px">Prioridad roadmap</th>
        <th style="text-align:center;width:110px">Crítica · Alta · Media</th>
        <th>Entornos afectados</th>
        <th style="width:120px">Avance UI</th>
        <th style="text-align:center;width:80px">AD promedio</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="font-size:11px;color:#9ca3af;margin-top:12px">
    Los colores en "Entornos afectados" indican la prioridad del entorno para esa funcionalidad:
    <span style="background:#fee2e2;color:#dc2626;padding:1px 6px;border-radius:6px">rojo = crítica</span>
    <span style="background:#ffedd5;color:#ea580c;padding:1px 6px;border-radius:6px">naranja = alta</span>
    <span style="background:#fef9c3;color:#ca8a04;padding:1px 6px;border-radius:6px">amarillo = media</span>
  </p>
</div>
"""


def build_modules_section(etendo_candidates: list, replaceable: list) -> str:
    rows_maint = ""
    for m in etendo_candidates:
        clients_str = ", ".join(m["clients"])
        multi_badge = (f'<span class="portfolio-pill p-multi">{m["client_count"]} cliente'
                       f'{"s" if m["client_count"] > 1 else ""}</span>') if m["client_count"] >= 2 else ""
        repl_badge = ('<span class="portfolio-pill p-norepl">Sin reemplazo</span>'
                      if not m["has_replacement"]
                      else '<span class="portfolio-pill p-repl">Reemplazo disponible</span>')
        gen_badge = f'<span class="portfolio-pill p-bundle">{m["generalization"]}</span>' if m["generalization"] else ""
        func_short = m["function"][:100] + "…" if len(m["function"]) > 100 else m["function"]
        rows_maint += (
            f'<tr>'
            f'<td><div style="font-weight:600;font-size:13px">{m["name"] or m["java_package"]}</div>'
            f'<div style="font-size:11px;color:#6b7280;font-family:monospace">{m["java_package"]}</div>'
            f'{gen_badge}</td>'
            f'<td style="font-size:12px;color:#374151">{func_short}</td>'
            f'<td style="font-size:12px">{clients_str}<br>{multi_badge}</td>'
            f'<td style="text-align:center">{_risk_badge(m["max_risk"])}</td>'
            f'<td>{repl_badge}</td>'
            f'<td style="text-align:center;white-space:nowrap;font-size:12px">'
            f'~{m["avg_effort_update_hours"]}h actualiz.<br>'
            f'<span style="color:#6b7280">~{m["avg_effort_saas_hours"]}h SaaS</span></td>'
            f'</tr>'
        )

    rows_repl = "".join(
        f'<tr>'
        f'<td style="font-size:12px;font-weight:600">{m["name"] or m["java_package"]}</td>'
        f'<td style="font-size:11px;color:#6b7280">{", ".join(m["clients"])}</td>'
        f'<td style="font-size:12px;color:#16a34a">→ {m["official_replacement_name"] or "—"}</td>'
        f'<td>{_risk_badge(m["max_risk"])}</td>'
        f'</tr>'
        for m in replaceable
    )

    top3 = " · ".join(f'<b>{m["name"] or m["java_package"]}</b>' for m in etendo_candidates[:3])

    return f"""
<div class="portfolio-section" id="portfolio-modules">
  <h2>Módulos sin mantenimiento — candidatos a soporte oficial</h2>
  <p class="portfolio-lead">
    Se identificaron <b>{len(etendo_candidates)} módulos</b> que requieren atención de Etendo:
    ya sea porque aparecen en múltiples clientes o porque son de riesgo alto sin reemplazo oficial.
    Los módulos con mayor prioridad son: {top3}.
    Tomar el mantenimiento de estos módulos o publicarlos como bundles oficiales reduciría
    significativamente el coste de migración del portfolio.
  </p>
  <h3>Candidatos a mantenimiento oficial por Etendo</h3>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Módulo</th><th>Función</th><th>Clientes</th>
        <th style="text-align:center">Riesgo</th><th>Reemplazo</th>
        <th style="text-align:center">Esfuerzo estimado</th>
      </tr>
    </thead>
    <tbody>{rows_maint}</tbody>
  </table>
  <h3>Módulos con reemplazo oficial disponible</h3>
  <p class="portfolio-lead" style="margin-bottom:10px">
    Estos módulos ya tienen un equivalente oficial en los bundles Etendo.
    La migración es una cuestión de validación de paridad funcional y migración de datos.
  </p>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Módulo</th><th>Clientes</th><th>Reemplazo oficial</th>
        <th style="text-align:center">Riesgo</th>
      </tr>
    </thead>
    <tbody>{rows_repl}</tbody>
  </table>
</div>
"""


def build_customizations_section(generalizable: list, etendo_candidates: list) -> str:
    core_items = [g for g in generalizable if g["type"] == "core"]
    module_items = [g for g in generalizable if g["type"] in ("module", "module_unmaintained")]

    # Deduplicate core items by name, merging clients
    seen_core: dict = {}
    for g in core_items:
        key = g["name"]
        if key not in seen_core:
            seen_core[key] = {"clients": [], "item": g}
        seen_core[key]["clients"].append(g["client"])

    rows_core = ""
    for key, data in seen_core.items():
        g = data["item"]
        multi_badge = '<span class="portfolio-pill p-multi">Varios clientes</span>' if len(data["clients"]) > 1 else ""
        clients_str = ", ".join(data["clients"])
        desc_short = g["description"][:120] + "…" if len(g["description"]) > 120 else g["description"]
        just_short = g["justification"][:120] + "…" if len(g["justification"]) > 120 else g["justification"]
        rows_core += (
            f'<tr>'
            f'<td><div style="font-weight:600;font-size:13px">{g["name"]}</div>{multi_badge}</td>'
            f'<td style="font-size:12px;color:#6b7280">{clients_str}</td>'
            f'<td style="font-size:12px">{desc_short}</td>'
            f'<td style="font-size:12px;color:#374151">{just_short}</td>'
            f'<td style="text-align:center;font-size:12px;white-space:nowrap">~{g["effort_saas_hours"]}h</td>'
            f'</tr>'
        )

    rows_modules = ""
    for g in module_items:
        type_badge = ('<span class="portfolio-pill p-bundle">bundle candidate</span>'
                      if g["type"] == "module"
                      else '<span class="portfolio-pill p-bundle">sin mantenimiento</span>')
        risk_str = f' · Riesgo: {g.get("risk", "")}' if g.get("risk") else ""
        desc_short = g.get("description", "")[:100] + "…" if len(g.get("description", "")) > 100 else g.get("description", "")
        rows_modules += (
            f'<tr>'
            f'<td><div style="font-weight:600;font-size:13px">{g["name"]}</div>'
            f'<div style="font-size:11px;color:#6b7280;font-family:monospace">{g.get("java_package", "")}</div>'
            f'{type_badge}</td>'
            f'<td style="font-size:12px;color:#6b7280">{g["client"]}</td>'
            f'<td style="font-size:12px">{desc_short}</td>'
            f'<td style="text-align:center;font-size:12px">{g.get("complexity", "")}{risk_str}</td>'
            f'<td style="text-align:center;font-size:12px;white-space:nowrap">~{g["effort_saas_hours"]}h</td>'
            f'</tr>'
        )

    total_saas = sum(g["effort_saas_hours"] for g in generalizable)

    return f"""
<div class="portfolio-section" id="portfolio-generalizable">
  <h2>Customizaciones generalizables — valor para el portfolio</h2>
  <p class="portfolio-lead">
    Se identificaron <b>{len(seen_core)} modificaciones de core</b> propuestas para upstream y
    <b>{len(module_items)} módulos</b> candidatos a bundle oficial. Si Etendo incorpora estas
    funcionalidades, el esfuerzo de migración SaaS del portfolio se reduce en aproximadamente
    <b>~{total_saas}h</b>.
  </p>
  <h3>Modificaciones de core propuestas para upstream</h3>
  <p class="portfolio-lead" style="margin-bottom:10px">
    Estas customizaciones son lo suficientemente genéricas como para ser parte del core de Etendo.
    Proponer su integración upstream eliminaría la necesidad de mantenerlas por separado en cada cliente.
  </p>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Customización</th><th>Cliente(s)</th><th>Descripción</th>
        <th>Justificación para upstream</th><th style="text-align:center">Esfuerzo SaaS</th>
      </tr>
    </thead>
    <tbody>{rows_core}</tbody>
  </table>
  <h3>Módulos candidatos a bundle oficial del marketplace</h3>
  <p class="portfolio-lead" style="margin-bottom:10px">
    Funcionalidades reutilizables que, publicadas como módulos oficiales en el marketplace de Etendo,
    reducirían la deuda técnica de múltiples clientes.
  </p>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Módulo</th><th>Cliente</th><th>Funcionalidad</th>
        <th>Complejidad / Riesgo</th><th style="text-align:center">Esfuerzo SaaS</th>
      </tr>
    </thead>
    <tbody>{rows_modules}</tbody>
  </table>
</div>
"""


PORTFOLIO_STYLES = """
<style>
.portfolio-table { width:100%; border-collapse:collapse; font-size:13px }
.portfolio-table th { background:#f8fafc; padding:8px 12px; text-align:left; font-weight:600; color:#374151; border-bottom:2px solid #e5e7eb }
.portfolio-table td { padding:8px 12px; border-bottom:1px solid #f3f4f6; vertical-align:top }
.portfolio-table tr:hover td { background:#fafafa }
.portfolio-section { background:#fff; border-radius:12px; padding:28px 32px; margin:24px 0; box-shadow:0 1px 4px rgba(0,0,0,.07) }
.portfolio-section h2 { font-size:20px; font-weight:700; color:#1e293b; margin:0 0 8px }
.portfolio-section h3 { font-size:15px; font-weight:600; color:#374151; margin:20px 0 8px }
.portfolio-lead { color:#64748b; font-size:13px; margin:0 0 18px; line-height:1.6 }
.portfolio-pill { display:inline-block; padding:1px 8px; border-radius:10px; font-size:11px; font-weight:600; margin:1px }
.p-repl { background:#dcfce7; color:#16a34a }
.p-norepl { background:#fee2e2; color:#dc2626 }
.p-multi { background:#dbeafe; color:#1d4ed8 }
.p-bundle { background:#ede9fe; color:#7c3aed }
.p-upstream { background:#d1fae5; color:#065f46 }
</style>
"""


def inject_into_dashboard(dashboard_path: Path, ui_section: str, modules_section: str, custom_section: str):
    html = dashboard_path.read_text()

    new_content = (
        "\n<!-- PORTFOLIO_ANALYSIS -->\n"
        + PORTFOLIO_STYLES
        + '<div style="max-width:1200px;margin:0 auto;padding:0 24px 48px">\n'
        + ui_section
        + modules_section
        + custom_section
        + "\n</div>\n"
        + "<!-- /PORTFOLIO_ANALYSIS -->\n"
    )

    if "<!-- PORTFOLIO_ANALYSIS -->" in html:
        html = re.sub(
            r"<!-- PORTFOLIO_ANALYSIS -->.*?<!-- /PORTFOLIO_ANALYSIS -->",
            new_content,
            html,
            flags=re.DOTALL,
        )
    else:
        html = html.replace("</body>", new_content + "</body>")

    dashboard_path.write_text(html)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    project_root = Path(__file__).parent.parent
    reports_dir = project_root / "reports"
    dashboard_path = reports_dir / "dashboard.html"

    print("Scanning reports…")
    analyzed = discover_reports(reports_dir)
    print(f"  Found {len(analyzed)} analyzed reports: {[a['slug'] for a in analyzed]}")

    if not analyzed:
        print("No analyzed reports found. Run /etendo-customisation-expert first.")
        sys.exit(0)

    print("Building UI feature roadmap…")
    feature_roadmap, ui_clients_meta = build_ui_feature_roadmap(analyzed)

    print("Building module candidates…")
    etendo_candidates, replaceable = build_module_candidates(analyzed)

    print("Building generalizable customizations…")
    generalizable = build_generalizable(analyzed, etendo_candidates)

    print("Saving portfolio_analysis.json…")
    save_portfolio_json(reports_dir, analyzed, feature_roadmap, ui_clients_meta, etendo_candidates, generalizable)

    print("Injecting sections into dashboard…")
    ui_html = build_ui_section(feature_roadmap, ui_clients_meta)
    modules_html = build_modules_section(etendo_candidates, replaceable)
    custom_html = build_customizations_section(generalizable, etendo_candidates)
    inject_into_dashboard(dashboard_path, ui_html, modules_html, custom_html)

    p1 = sum(1 for f in feature_roadmap if len(f["clients_critica"]) >= 2)
    p2 = sum(1 for f in feature_roadmap if len(f["clients_critica"]) == 1 and f["portfolio_score"] >= 4)
    total_saas = sum(g["effort_saas_hours"] for g in generalizable)
    print(
        f"\n✓ Portfolio analysis complete:\n"
        f"  UI roadmap: {len(feature_roadmap)} features · {p1} P1 (inmediata) · {p2} P2 (alta)\n"
        f"  Module candidates: {len(etendo_candidates)} for Etendo · {len(replaceable)} with replacement\n"
        f"  Generalizable: {len([g for g in generalizable if g['type']=='core'])} core upstreams · "
        f"{len([g for g in generalizable if g['type'] in ('module','module_unmaintained')])} bundle candidates\n"
        f"  Estimated SaaS savings if upstreamed: ~{total_saas}h"
    )


if __name__ == "__main__":
    main()
