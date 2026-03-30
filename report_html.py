#!/usr/bin/env python3
"""
report_html.py — Generates an HTML migration report from a JSON report file.

Usage:
    python3 report_html.py --input report.json --output report.html
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Generate HTML report from JSON")
    parser.add_argument("--input", required=True, help="Input JSON report")
    parser.add_argument("--output", default="report.html", help="Output HTML file")
    return parser.parse_args()


# ── helpers ──────────────────────────────────────────────────────────────────

def score_color(score):
    if score >= 80:
        return "#22c55e"
    if score >= 60:
        return "#f59e0b"
    if score >= 40:
        return "#f97316"
    return "#ef4444"


def migratability_label_es(label):
    return {
        "easy":      "Fácil",
        "moderate":  "Moderada",
        "hard":      "Difícil",
        "very_hard": "Muy difícil",
    }.get(label, label)


def breakdown_label(key):
    return {
        "openbravo_platform":          "Plataforma Openbravo",
        "core_divergences":            "Divergencias en core",
        "local_not_maintained":        "Módulos locales sin mantenimiento",
        "custom_modules":              "Customizaciones",
        "local_maintained_divergences":"Divergencias en módulos locales mantenidos",
        "gradle_source_divergences":   "Divergencias en dependencias Gradle Sources",
        "jar_dependency_outdated":     "Dependencias Gradle JAR desactualizadas",
    }.get(key, key)


def category_label(cat):
    return {
        "gradle_jar":          "Dependencias Gradle JAR",
        "gradle_source":       "Dependencias Gradle Sources",
        "local_maintained":    "Módulos Locales Mantenidos",
        "local_not_maintained":"Módulos Locales sin Mantenimiento",
        "custom":              "Customizaciones",
    }.get(cat, cat)


def category_color(cat):
    return {
        "gradle_jar":          "#0ea5e9",
        "gradle_source":       "#22c55e",
        "local_maintained":    "#3b82f6",
        "local_not_maintained":"#f97316",
        "custom":              "#a855f7",
    }.get(cat, "#6b7280")


def category_icon(cat):
    return {
        "gradle_jar":          "⬡",
        "gradle_source":       "✓",
        "local_maintained":    "↑",
        "local_not_maintained":"⚠",
        "custom":              "✎",
    }.get(cat, "•")


def fmt_int(v):
    return str(v) if v is not None else "—"


def _parse_version(v):
    """Convert '1.4.2' → (1, 4, 2) for comparison."""
    if not v:
        return ()
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def version_gap_html(installed, latest):
    """
    Returns HTML showing installed → latest with a colored gap badge.
    Gap levels: none / patch / minor / major
    """
    if not installed or not latest:
        return ""

    iv = _parse_version(installed)
    lv = _parse_version(latest)

    if not iv or not lv:
        return ""

    if lv <= iv:
        # up-to-date or ahead
        badge_cls = "gap-ok"
        badge_txt = "al día"
        arrow_cls = "gap-arrow-ok"
    elif len(iv) >= 1 and len(lv) >= 1 and lv[0] > iv[0]:
        badge_cls = "gap-major"
        badge_txt = "major"
        arrow_cls = "gap-arrow-major"
    elif len(iv) >= 2 and len(lv) >= 2 and lv[1] > iv[1]:
        badge_cls = "gap-minor"
        badge_txt = "minor"
        arrow_cls = "gap-arrow-minor"
    else:
        badge_cls = "gap-patch"
        badge_txt = "patch"
        arrow_cls = "gap-arrow-patch"

    return (
        f'<span class="ver-installed">v{installed}</span>'
        f'<span class="{arrow_cls}">→</span>'
        f'<span class="ver-latest">v{latest}</span>'
        f'<span class="gap-badge {badge_cls}">{badge_txt}</span>'
    )


# ── render sections ───────────────────────────────────────────────────────────

def render_score_ring(score, label):
    color = score_color(score)
    r = 54
    circ = 2 * 3.14159 * r
    filled = circ * score / 100
    gap = circ - filled
    return f"""
<div class="score-ring-wrap">
  <svg viewBox="0 0 120 120" class="score-ring">
    <circle cx="60" cy="60" r="{r}" fill="none" stroke="#e5e7eb" stroke-width="10"/>
    <circle cx="60" cy="60" r="{r}" fill="none" stroke="{color}" stroke-width="10"
      stroke-dasharray="{filled:.1f} {gap:.1f}"
      stroke-dashoffset="{circ/4:.1f}"
      stroke-linecap="round"/>
    <text x="60" y="56" text-anchor="middle" font-size="22" font-weight="700" fill="{color}">{score}</text>
    <text x="60" y="73" text-anchor="middle" font-size="9" fill="#6b7280">/100</text>
  </svg>
  <div class="score-label" style="color:{color}">{migratability_label_es(label)}</div>
</div>"""


def render_breakdown(breakdown, final_score):
    # Keys to show (in order), excluding internal/detail keys
    _SKIP = {"custom_modules_detail", "core_diff_lines",
             "local_not_maintained_translations", "local_not_maintained_regular"}
    _ORDER = [
        "openbravo_platform",
        "core_divergences",
        "local_not_maintained",
        "custom_modules",
        "local_maintained_divergences",
        "gradle_source_divergences",
        "jar_dependency_outdated",
    ]
    # Maximum cap for each penalty category (from scoring formula)
    # local_not_maintained = regular cap (-20) + translations cap (-3) = -23
    _CAPS = {
        "openbravo_platform":           -20,
        "core_divergences":             -15,
        "local_not_maintained":         -23,
        "custom_modules":               -35,
        "local_maintained_divergences": -15,
        "gradle_source_divergences":    -15,
        "jar_dependency_outdated":      -10,
    }

    numeric = {k: v for k, v in breakdown.items()
               if k not in _SKIP and isinstance(v, (int, float))}
    total_penalty = sum(v for v in numeric.values() if v < 0)
    max_abs = max((abs(v) for v in numeric.values()), default=1) or 1

    rows = ""
    # Base score row
    rows += f"""
      <tr class="bd-row-base">
        <td class="bd-label">Puntuación base</td>
        <td class="bd-bar-cell"><div class="bd-bar bd-bar-base" style="width:100%"></div></td>
        <td class="bd-val bd-val-base">100</td>
      </tr>"""

    # Penalty rows (ordered, skip zeroes)
    for key in _ORDER:
        val = numeric.get(key)
        if val is None or val == 0:
            continue
        cap = _CAPS.get(key)
        cap_html = f'<span class="bd-cap"> / {cap:.0f}</span>' if cap else ""
        pct = abs(val) / max_abs * 100
        rows += f"""
      <tr class="bd-row-penalty">
        <td class="bd-label">{breakdown_label(key)}</td>
        <td class="bd-bar-cell">
          <div class="bd-bar bd-bar-neg" style="width:{pct:.1f}%"></div>
        </td>
        <td class="bd-val bd-val-neg">{val:+.1f}{cap_html}</td>
      </tr>"""

    # Separator + total penalty
    rows += f"""
      <tr class="bd-row-sep"><td colspan="3"><div class="bd-sep-line"></div></td></tr>
      <tr class="bd-row-total">
        <td class="bd-label bd-label-total">Total penalizaciones</td>
        <td class="bd-bar-cell"></td>
        <td class="bd-val bd-val-neg">{total_penalty:+.1f}</td>
      </tr>
      <tr class="bd-row-result">
        <td class="bd-label bd-label-result">Score final</td>
        <td class="bd-bar-cell">
          <div class="bd-bar bd-bar-result" style="width:{final_score}%;background:{score_color(final_score)}"></div>
        </td>
        <td class="bd-val bd-val-result" style="color:{score_color(final_score)}">{final_score}</td>
      </tr>"""

    return f"""
<table class="breakdown-table">
  <tbody>{rows}
  </tbody>
</table>"""


def render_module_row(mod, show_diff=True, is_custom=False):
    diff       = mod.get("diff") if show_diff else None
    installed  = mod.get("version")
    latest     = mod.get("latest_version")
    author     = mod.get("author") or ""
    bundle     = mod.get("bundle") or ""

    ver_html = version_gap_html(installed, latest)
    if not ver_html and installed:
        ver_html = f'<span class="ver-installed">v{installed}</span>'

    diff_html = ""
    if diff:
        diff_html = f"""
      <div class="mod-diff">
        <span class="diff-badge df">{diff['modified_files']} con diferencias</span>
        <span class="diff-badge add">+{diff['added_files']} nuevos</span>
        <span class="diff-badge del">-{diff['deleted_files']} eliminados</span>
        <span class="diff-badge lines">+{diff['diff_lines_added']} / -{diff['diff_lines_removed']} líneas</span>
      </div>"""

    custom_html = ""
    if is_custom:
        loc       = mod.get("line_count", 0)
        size      = mod.get("custom_size") or {}
        tier_key  = size.get("key", "")
        tier_lbl  = size.get("label", "—")
        tier_cls  = {"micro": "tier-micro", "small": "tier-small",
                     "medium": "tier-medium", "large": "tier-large",
                     "translation": "tier-translation"}.get(tier_key, "tier-medium")
        tier_penalties = {"micro": 1, "small": 4, "medium": 9, "large": 16}
        pen = tier_penalties.get(tier_key, 9)
        custom_html = f"""
      <div class="custom-detail">
        <span class="loc-badge">{loc:,} LOC</span>
        <span class="tier-badge {tier_cls}">{tier_lbl}</span>
        <span class="pen-badge">penalización: {pen:+d}</span>
      </div>"""

    import re as _re
    _LOCALE_RE = _re.compile(r'[._][a-z]{2}[._][a-zA-Z]{2}$')
    is_translation = bool(_LOCALE_RE.search(mod.get('java_package', '')))
    translation_badge = "<span class='translation-badge'>🌐 traducción</span>" if is_translation else ""

    return f"""
    <tr class="mod-row">
      <td class="mod-pkg"><span class="pkg">{mod['java_package']}</span>{translation_badge}</td>
      <td class="mod-meta">
        <div class="ver-row">{ver_html}</div>
        {"<span class='author'>" + author + "</span>" if author else ""}
        {"<span class='bundle'>" + bundle + "</span>" if bundle else ""}
        {diff_html}{custom_html}
      </td>
    </tr>"""


def render_modules(modules):
    order = ["gradle_jar", "gradle_source", "local_maintained", "local_not_maintained", "custom"]
    blocks = ""
    for cat in order:
        mods = modules.get(cat, [])
        color = category_color(cat)
        icon  = category_icon(cat)
        label = category_label(cat)
        count = len(mods)
        show_diff = cat in ("gradle_source", "local_maintained")

        rows = "".join(render_module_row(m, show_diff, is_custom=(cat == "custom")) for m in mods)
        table = f"<table class='mod-table'><tbody>{rows}</tbody></table>" if mods else "<p class='empty'>Sin módulos en esta categoría.</p>"

        blocks += f"""
<div class="module-block">
  <div class="module-header" onclick="toggle(this)" style="border-left:4px solid {color}">
    <span class="cat-icon" style="color:{color}">{icon}</span>
    <span class="cat-label">{label}</span>
    <span class="cat-count" style="background:{color}">{count}</span>
    <span class="chevron">▾</span>
  </div>
  <div class="module-body">
    {table}
  </div>
</div>"""
    return blocks


def render_core(core):
    status = core.get("status", "no_base")
    if status == "no_base":
        return "<p class='empty'>No se encontró base de comparación (etendo-core-*.zip).</p>"

    files = core.get("files", [])
    divergent = sorted(
        [f for f in files if f["status"] == "modified"],
        key=lambda x: x["lines_added"] + x["lines_removed"],
        reverse=True
    )[:20]
    other = [f for f in files if f["status"] in ("added", "deleted")]

    rows = ""
    for f in divergent:
        total = f["lines_added"] + f["lines_removed"]
        rows += f"""
    <tr>
      <td class="file-path">{f['path']}</td>
      <td class="file-add">+{f['lines_added']}</td>
      <td class="file-del">-{f['lines_removed']}</td>
      <td class="file-total">{total}</td>
    </tr>"""

    for f in other:
        badge_cls = "status-added" if f["status"] == "added" else "status-deleted"
        badge_lbl = "nuevo" if f["status"] == "added" else "eliminado"
        rows += f"""
    <tr>
      <td class="file-path">{f['path']} <span class="status-badge {badge_cls}">{badge_lbl}</span></td>
      <td class="file-add">—</td><td class="file-del">—</td><td class="file-total">—</td>
    </tr>"""

    return f"""
<p class="core-note">
  Las diferencias incluyen tanto customizaciones como desactualización de versión.
  Base de comparación: <strong>v{core.get('base_version', '—')}</strong>.
</p>
<div class="core-stats">
  <div class="stat-pill"><strong>{fmt_int(core['modified_files'])}</strong><span>con diferencias</span></div>
  <div class="stat-pill"><strong>{fmt_int(core['added_files'])}</strong><span>archivos nuevos</span></div>
  <div class="stat-pill"><strong>{fmt_int(core['deleted_files'])}</strong><span>archivos eliminados</span></div>
  <div class="stat-pill add-pill"><strong>+{fmt_int(core['diff_lines_added'])}</strong><span>líneas</span></div>
  <div class="stat-pill del-pill"><strong>-{fmt_int(core['diff_lines_removed'])}</strong><span>líneas</span></div>
</div>
<table class="file-table">
  <thead>
    <tr><th>Archivo</th><th>Líneas +</th><th>Líneas -</th><th>Total</th></tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def render_methodology():
    return """
<div class="meth-grid">

  <div class="meth-block">
    <div class="meth-title">Categorías de módulos</div>
    <table class="meth-table">
      <thead><tr><th>Categoría</th><th>Descripción</th><th>Cómo se penaliza</th><th>Por qué</th></tr></thead>
      <tbody>
        <tr><td><span class="cat-chip chip-jar">Gradle JAR</span></td>
            <td>Módulos resueltos como binarios (JARs) por Gradle. No tienen código fuente editable en la instalación.</td>
            <td>Solo se penaliza si están desactualizados:<br>
                −0.15 por módulo con gap <em>major</em> (máximo −3)<br>
                −0.05 por módulo con gap <em>minor/patch</em> (máximo −1)</td>
            <td>Actualizar un JAR es solo cambiar el número de versión en build.gradle. Sin riesgo de pérdida de código. Es el escenario ideal de migración.</td></tr>
        <tr><td><span class="cat-chip chip-src">Gradle Sources</span></td>
            <td>Módulos cuyo bundle está declarado en build.gradle pero tienen fuentes expandidas en /modules/. Deberían ser JAR pero alguien los desempaquetó.</td>
            <td>−0.1 por cada archivo con diferencias respecto a la versión limpia (máximo −5 por módulo)</td>
            <td>Tener el fuente local indica posibles divergencias. La penalización es baja porque el módulo sigue siendo soportado y la ruta de migración es volver a JAR.</td></tr>
        <tr><td><span class="cat-chip chip-mnt">Local Mantenido</span></td>
            <td>Módulo con código fuente en /modules/, reconocido en el catálogo de Etendo pero no declarado como dependencia Gradle. Puede tener divergencias respecto a la versión publicada.</td>
            <td>−0.2 por cada archivo con diferencias respecto a la versión limpia (máximo −10 por módulo)</td>
            <td>Mayor penalización que Gradle Sources porque no está gestionado como dependencia. Cada archivo divergente implica trabajo de análisis para determinar si es customización o desactualización.</td></tr>
        <tr><td><span class="cat-chip chip-nmnt">Local sin Mant.</span></td>
            <td>Módulo con código fuente en /modules/ que no aparece en el catálogo de Etendo. Puede ser de terceros, legacy de Openbravo, o un módulo abandonado.</td>
            <td>−3 por módulo, independientemente del contenido (máximo −20)</td>
            <td>Sin soporte oficial no hay ruta de actualización garantizada. Cada uno requiere evaluación manual para decidir si se reemplaza, se integra como customización, o se descarta.</td></tr>
        <tr><td><span class="cat-chip chip-cust">Customización</span></td>
            <td>Módulo desarrollado por o para el cliente (el java_package contiene el nombre del cliente o el segmento "custom"). Representa lógica de negocio propia.</td>
            <td>Penalización escalonada por volumen de código (LOC). Ver tabla de tamaños. Máximo global −35.</td>
            <td>Las customizaciones son el mayor obstáculo para migrar a SaaS: deben generalizarse o reescribirse. A mayor volumen de código, mayor el esfuerzo estimado de análisis y portabilidad.</td></tr>
      </tbody>
    </table>
  </div>

  <div class="meth-block">
    <div class="meth-title">Tamaño de customizaciones (LOC)</div>
    <table class="meth-table">
      <thead><tr><th>Tamaño</th><th>LOC</th><th>Penalización</th><th>Criterio</th></tr></thead>
      <tbody>
        <tr><td><span class="tier-badge tier-micro">micro</span></td>
            <td>&lt; 500</td><td>−1</td>
            <td>Adaptación puntual, fácil de generalizar.</td></tr>
        <tr><td><span class="tier-badge tier-small">small</span></td>
            <td>500 – 2.000</td><td>−4</td>
            <td>Funcionalidad acotada, esfuerzo de análisis moderado.</td></tr>
        <tr><td><span class="tier-badge tier-medium">medium</span></td>
            <td>2.000 – 8.000</td><td>−9</td>
            <td>Módulo con lógica propia. Requiere diseño para generalizar.</td></tr>
        <tr><td><span class="tier-badge tier-large">large</span></td>
            <td>&gt; 8.000</td><td>−16</td>
            <td>Desarrollo significativo. Alta complejidad de migración.</td></tr>
      </tbody>
    </table>
    <p class="meth-note">Máximo global de customizaciones: −35. El LOC se cuenta sobre archivos de texto
    (.java, .xml, .sql, .js, .css, .html, .properties, .gradle, etc.).</p>
  </div>

  <div class="meth-block">
    <div class="meth-title">Core y otros factores</div>
    <table class="meth-table">
      <thead><tr><th>Factor</th><th>Penalización</th></tr></thead>
      <tbody>
        <tr><td>Plataforma Openbravo (sin build.gradle)</td><td>−20 fijo</td></tr>
        <tr><td>Líneas de diferencia en core (por cada 100)</td><td>−0.5 (máximo −15)</td></tr>
      </tbody>
    </table>
    <p class="meth-note">Las diferencias en core incluyen tanto customizaciones como brecha de versión
    (el cliente puede estar en una versión anterior a la base de comparación). El score parte de 100
    y se le restan todas las penalizaciones.</p>
  </div>

  <div class="meth-block">
    <div class="meth-title">Escala de migratabilidad</div>
    <table class="meth-table">
      <thead><tr><th>Score</th><th>Nivel</th><th>Significado</th></tr></thead>
      <tbody>
        <tr><td>80 – 100</td><td><span class="mig-badge mig-easy">Fácil</span></td>
            <td>Migración directa. Principalmente actualizaciones de versión.</td></tr>
        <tr><td>60 – 79</td><td><span class="mig-badge mig-mod">Moderada</span></td>
            <td>Requiere trabajo de adaptación pero es manejable.</td></tr>
        <tr><td>40 – 59</td><td><span class="mig-badge mig-hard">Difícil</span></td>
            <td>Presencia significativa de customizaciones o módulos no mantenidos.</td></tr>
        <tr><td>0 – 39</td><td><span class="mig-badge mig-vhard">Muy difícil</span></td>
            <td>Customizaciones extensas o core muy divergente. Proyecto de mediano plazo.</td></tr>
      </tbody>
    </table>
  </div>

</div>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #f8fafc; color: #1e293b; font-size: 14px; }

.page { max-width: 1000px; margin: 0 auto; padding: 24px 16px; }

/* Header */
.report-header { background: #1e293b; color: #f1f5f9; padding: 28px 32px;
                 border-radius: 12px; margin-bottom: 24px; }
.report-header h1 { font-size: 22px; font-weight: 700; }
.report-header .sub { font-size: 13px; color: #94a3b8; margin-top: 6px; }
.header-meta { display: flex; gap: 24px; margin-top: 16px; flex-wrap: wrap; }
.meta-item { font-size: 13px; }
.meta-item strong { color: #e2e8f0; }
.meta-item span { color: #94a3b8; }

/* Cards */
.card { background: #fff; border-radius: 10px; border: 1px solid #e2e8f0;
        padding: 20px 24px; margin-bottom: 20px; }
.card h2 { font-size: 15px; font-weight: 600; color: #374151; margin-bottom: 16px;
           padding-bottom: 10px; border-bottom: 1px solid #f1f5f9; }

/* Score section */
.score-section { display: flex; gap: 32px; align-items: flex-start; flex-wrap: wrap; }
.score-ring-wrap { text-align: center; }
.score-ring { width: 120px; height: 120px; }
.score-label { font-size: 14px; font-weight: 600; margin-top: 6px; }
.score-right { flex: 1; min-width: 240px; }
.breakdown-table { width: 100%; border-collapse: collapse; }
.breakdown-table td { padding: 5px 4px; vertical-align: middle; }
.bd-label { font-size: 12px; color: #475569; white-space: nowrap; width: 240px; }
.bd-bar-cell { padding: 0 12px; }
.bd-bar { height: 8px; border-radius: 4px; min-width: 4px; }
.bd-bar-base { background: #22c55e; }
.bd-bar-neg  { background: #ef4444; }
.bd-val { font-size: 12px; font-weight: 600; text-align: right; white-space: nowrap; }
.bd-val-base { color: #22c55e; }
.bd-val-neg  { color: #ef4444; }
.bd-cap { font-size: 11px; font-weight: 400; color: #9ca3af; }
.bd-val-result { font-size: 14px; }
.bd-row-base td { padding-bottom: 8px; }
.bd-row-sep td { padding: 4px 0; }
.bd-sep-line { border-top: 1px solid #e2e8f0; }
.bd-row-total td { padding-top: 4px; }
.bd-label-total  { font-weight: 600; color: #334155; }
.bd-row-result td { padding-top: 8px; border-top: 2px solid #e2e8f0; }
.bd-label-result { font-weight: 700; font-size: 13px; color: #0f172a; }

/* Module pills */
.module-pills { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px; }
.module-pill { display: flex; align-items: center; gap: 8px; padding: 10px 16px;
               border-radius: 8px; border: 1px solid #e2e8f0; background: #f8fafc; }
.pill-icon { font-size: 18px; font-weight: 700; }
.pill-info strong { display: block; font-size: 18px; font-weight: 700; }
.pill-info span  { font-size: 11px; color: #6b7280; }

/* Module blocks */
.module-block { margin-bottom: 8px; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.module-header { display: flex; align-items: center; gap: 10px; padding: 12px 16px;
                 cursor: pointer; background: #f8fafc; user-select: none; }
.module-header:hover { background: #f1f5f9; }
.cat-icon { font-size: 16px; font-weight: 700; width: 20px; text-align: center; }
.cat-label { font-size: 13px; font-weight: 600; flex: 1; }
.cat-count { font-size: 12px; font-weight: 700; color: #fff; padding: 2px 8px; border-radius: 12px; }
.chevron { font-size: 12px; color: #9ca3af; transition: transform 0.2s; }
.module-header.open .chevron { transform: rotate(180deg); }
.module-body { display: none; padding: 0 16px 12px; }
.module-body.open { display: block; }

/* Module table */
.mod-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.mod-row td { padding: 7px 4px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.mod-row:last-child td { border-bottom: none; }
.mod-pkg { width: 50%; }
.pkg { font-size: 12px; font-family: 'SF Mono', Consolas, monospace; color: #1e293b; word-break: break-all; }

/* Version gap */
.ver-row { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin-bottom: 3px; }
.ver-installed { font-size: 12px; color: #475569; background: #f1f5f9; padding: 2px 7px;
                 border-radius: 4px; font-family: 'SF Mono', Consolas, monospace; }
.ver-latest { font-size: 12px; color: #1e293b; background: #e0f2fe; padding: 2px 7px;
              border-radius: 4px; font-family: 'SF Mono', Consolas, monospace; font-weight: 600; }
.gap-arrow-ok     { font-size: 11px; color: #22c55e; }
.gap-arrow-patch  { font-size: 11px; color: #f59e0b; }
.gap-arrow-minor  { font-size: 11px; color: #f97316; }
.gap-arrow-major  { font-size: 11px; color: #ef4444; }
.gap-badge { font-size: 10px; padding: 2px 6px; border-radius: 10px; font-weight: 600;
             text-transform: uppercase; letter-spacing: 0.03em; }
.gap-ok     { background: #dcfce7; color: #166534; }
.gap-patch  { background: #fef9c3; color: #854d0e; }
.gap-minor  { background: #ffedd5; color: #9a3412; }
.gap-major  { background: #fee2e2; color: #991b1b; }

.author { font-size: 11px; color: #9ca3af; margin-right: 4px; }
.bundle { font-size: 11px; color: #3b82f6; background: #eff6ff; padding: 1px 6px; border-radius: 4px; }

/* Diff badges */
.mod-diff { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; }
.diff-badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.diff-badge.df    { background: #fef3c7; color: #92400e; }
.diff-badge.add   { background: #dcfce7; color: #166534; }
.diff-badge.del   { background: #fee2e2; color: #991b1b; }
.diff-badge.lines { background: #f3f4f6; color: #374151; }

/* Core */
.core-note { font-size: 12px; color: #6b7280; background: #f8fafc; border: 1px solid #e2e8f0;
             border-radius: 6px; padding: 8px 12px; margin-bottom: 16px; }
.core-stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.stat-pill { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
             padding: 10px 16px; text-align: center; }
.stat-pill strong { display: block; font-size: 20px; font-weight: 700; color: #1e293b; }
.stat-pill span   { font-size: 11px; color: #6b7280; }
.stat-pill.add-pill strong { color: #16a34a; }
.stat-pill.del-pill strong { color: #dc2626; }

.file-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.file-table th { text-align: left; padding: 6px 8px; background: #f8fafc;
                 border-bottom: 2px solid #e2e8f0; font-size: 11px; color: #6b7280;
                 font-weight: 600; white-space: nowrap; }
.file-table td { padding: 5px 8px; border-bottom: 1px solid #f8fafc; }
.file-table tr:hover td { background: #f8fafc; }
.file-path { font-family: 'SF Mono', Consolas, monospace; color: #1e293b; word-break: break-all; }
.file-add  { color: #16a34a; font-weight: 600; text-align: right; white-space: nowrap; }
.file-del  { color: #dc2626; font-weight: 600; text-align: right; white-space: nowrap; }
.file-total{ color: #6b7280; text-align: right; white-space: nowrap; }
.status-badge { font-size: 10px; padding: 1px 6px; border-radius: 4px; }
.status-added   { background: #dcfce7; color: #166534; }
.status-deleted { background: #fee2e2; color: #991b1b; }

.empty { color: #9ca3af; font-size: 13px; font-style: italic; padding: 8px 0; }
.footer { text-align: center; font-size: 11px; color: #9ca3af; margin-top: 32px; }

/* Translation badge */
.translation-badge {
    display: inline-block;
    margin-left: 8px;
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 4px;
    background: #f1f5f9;
    color: #64748b;
    font-weight: 600;
    vertical-align: middle;
    letter-spacing: 0.02em;
}

/* Custom module detail */
.custom-detail { margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.loc-badge { font-size: 10px; padding: 2px 7px; border-radius: 4px;
             background: #f3f4f6; color: #374151; font-family: 'SF Mono', Consolas, monospace; }
.pen-badge { font-size: 10px; padding: 2px 7px; border-radius: 4px;
             background: #fef2f2; color: #991b1b; font-weight: 600; }
.tier-badge { font-size: 10px; padding: 2px 7px; border-radius: 4px; font-weight: 600;
              text-transform: uppercase; letter-spacing: 0.03em; }
.tier-micro  { background: #f0fdf4; color: #166534; }
.tier-small       { background: #fefce8; color: #854d0e; }
.tier-medium      { background: #fff7ed; color: #9a3412; }
.tier-large       { background: #fef2f2; color: #991b1b; }
.tier-translation { background: #f1f5f9; color: #64748b; }

/* Methodology */
.meth-grid { display: grid; grid-template-columns: 1fr; gap: 20px; }
.meth-block { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px 20px; }
.meth-title { font-size: 13px; font-weight: 700; color: #1e293b; margin-bottom: 12px;
              padding-bottom: 8px; border-bottom: 1px solid #e2e8f0; }
.meth-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.meth-table th { text-align: left; padding: 5px 8px; background: #f1f5f9;
                 border-bottom: 2px solid #e2e8f0; font-size: 11px; color: #6b7280;
                 font-weight: 600; white-space: nowrap; }
.meth-table td { padding: 6px 8px; border-bottom: 1px solid #f1f5f9; vertical-align: top; color: #374151; }
.meth-table tr:last-child td { border-bottom: none; }
.meth-note { font-size: 11px; color: #6b7280; margin-top: 10px; line-height: 1.5; }

/* Category chips */
.cat-chip { font-size: 10px; padding: 2px 8px; border-radius: 10px; font-weight: 600;
            white-space: nowrap; }
.chip-jar  { background: #e0f2fe; color: #0369a1; }
.chip-src  { background: #dcfce7; color: #166534; }
.chip-mnt  { background: #dbeafe; color: #1d4ed8; }
.chip-nmnt { background: #ffedd5; color: #9a3412; }
.chip-cust { background: #f3e8ff; color: #7e22ce; }

/* Migratability badges */
.mig-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.mig-easy  { background: #dcfce7; color: #166534; }
.mig-mod   { background: #fef9c3; color: #854d0e; }
.mig-hard  { background: #ffedd5; color: #9a3412; }
.mig-vhard { background: #fee2e2; color: #991b1b; }

/* ── Custom Assessor ────────────────────────────────────────────────────── */
.asmnt-meta { font-size: 12px; color: #64748b; margin-bottom: 16px; }
.asmnt-section-label { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.5px; color: #94a3b8; margin: 18px 0 10px; }
.asmnt-badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.3px; }
.asmnt-trivial  { background: #dcfce7; color: #166534; }
.asmnt-minor    { background: #fef9c3; color: #854d0e; }
.asmnt-major    { background: #fee2e2; color: #991b1b; }
.asmnt-critical { background: #fce7f3; color: #9d174d; }
.asmnt-type     { background: #e0f2fe; color: #075985; }
.asmnt-effort { font-size: 11px; color: #64748b; background: #f1f5f9;
  padding: 2px 7px; border-radius: 4px; white-space: nowrap; }
.asmnt-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.asmnt-table th { text-align: left; padding: 7px 10px; background: #f8fafc;
  color: #64748b; font-weight: 600; border-bottom: 2px solid #e2e8f0;
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; }
.asmnt-table td { padding: 8px 10px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }
.asmnt-table tr:last-child td { border-bottom: none; }
.asmnt-table tr:hover td { background: #f8fafc; }
.asmnt-desc { color: #475569; font-size: 12px; margin-top: 3px; }
.asmnt-rec  { color: #0f172a; font-size: 12px; }
.asmnt-row-high td { background: #fff5f5; }
.asmnt-row-med  td { background: #fffbeb; }
.asmnt-effort-box { background: #1e293b; color: #f1f5f9; border-radius: 8px;
  padding: 14px 20px; margin-top: 12px; display: flex; gap: 32px; flex-wrap: wrap; }
.asmnt-stat { text-align: center; }
.asmnt-stat-total { border-left: 1px solid #334155; padding-left: 32px; }
.asmnt-stat-val       { font-size: 22px; font-weight: 700; color: #38bdf8; }
.asmnt-stat-val-total { font-size: 22px; font-weight: 700; color: #f97316; }
.asmnt-stat-lbl { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.asmnt-note { font-size: 11px; color: #94a3b8; margin-top: 10px; }
"""

JS = """
function toggle(header) {
  header.classList.toggle('open');
  header.nextElementSibling.classList.toggle('open');
}
document.addEventListener('DOMContentLoaded', function() {
  var first = document.querySelector('.module-header');
  if (first) toggle(first);
});
"""


# ── assessment render ─────────────────────────────────────────────────────────

_COMPLEXITY_CLS = {
    "trivial":  "asmnt-trivial",
    "minor":    "asmnt-minor",
    "major":    "asmnt-major",
    "critical": "asmnt-critical",
}
_RISK_CLS = {
    "low":    "asmnt-trivial",
    "medium": "asmnt-minor",
    "high":   "asmnt-major",
}
_RISK_ROW = {
    "high":   " asmnt-row-high",
    "medium": " asmnt-row-med",
    "low":    "",
}


def _abadge(cls, label):
    return f'<span class="asmnt-badge {cls}">{label}</span>'


def _effort_tag(s):
    return f'<span class="asmnt-effort">{s}</span>'


def _fmt_effort_range(lo, hi):
    if lo == hi:
        return f"{lo:.0f}"
    return f"{lo:.0f}–{hi:.0f}"


def render_assessment(assessment):
    if not assessment:
        return ""

    core_items   = assessment.get("core_customizations", [])
    custom_items = assessment.get("custom_modules", [])
    unm_items    = assessment.get("unmaintained_modules", [])
    effort       = assessment.get("effort_summary", {})
    generated    = assessment.get("generated", "")

    # ── Core section ──────────────────────────────────────────────────────
    core_html = ""
    if core_items:
        rows = ""
        for item in core_items:
            cx  = item.get("complexity", "minor")
            rows += f"""
          <tr>
            <td>
              <strong>{item.get('name','')}</strong>
              <div class="asmnt-desc">{item.get('description','')}</div>
            </td>
            <td><span class="asmnt-badge asmnt-type">{item.get('type','')}</span></td>
            <td>{_abadge(_COMPLEXITY_CLS.get(cx,'asmnt-minor'), cx.capitalize())}</td>
            <td>{_effort_tag(item.get('effort_days','?'))}</td>
            <td class="asmnt-rec">{item.get('recommendation','')}</td>
          </tr>"""
        core_html = f"""
      <div class="asmnt-section-label">1 · Modificaciones al Core</div>
      <table class="asmnt-table">
        <thead><tr>
          <th>Customización</th><th>Tipo</th><th>Complejidad</th>
          <th>Esfuerzo</th><th>Acción recomendada</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>"""

    # ── Custom modules section ────────────────────────────────────────────
    custom_html = ""
    if custom_items:
        rows = ""
        for item in custom_items:
            risk = item.get("risk", "low")
            rows += f"""
          <tr class="{_RISK_ROW.get(risk, '')}">
            <td><strong>{item.get('java_package','')}</strong></td>
            <td>{item.get('function','')}</td>
            <td>{_abadge(_RISK_CLS.get(risk,'asmnt-trivial'), risk.capitalize())}</td>
            <td>{_effort_tag(item.get('effort_days','?'))}</td>
            <td class="asmnt-rec">{item.get('recommendation','')}</td>
          </tr>"""
        custom_html = f"""
      <div class="asmnt-section-label">2 · Módulos Custom</div>
      <table class="asmnt-table">
        <thead><tr>
          <th>Módulo</th><th>Función</th><th>Riesgo</th>
          <th>Esfuerzo</th><th>Recomendación</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>"""

    # ── Unmaintained modules section ──────────────────────────────────────
    unm_html = ""
    if unm_items:
        rows = ""
        for item in unm_items:
            risk   = item.get("risk", "low")
            repl   = "✅" if item.get("has_official_replacement") else "❌"
            rows += f"""
          <tr class="{_RISK_ROW.get(risk, '')}">
            <td><strong>{item.get('java_package','')}</strong></td>
            <td>{item.get('function','')}</td>
            <td>{_abadge(_RISK_CLS.get(risk,'asmnt-trivial'), risk.capitalize())}</td>
            <td style="text-align:center;font-size:14px">{repl}</td>
            <td>{_effort_tag(item.get('effort_days','?'))}</td>
            <td class="asmnt-rec">{item.get('recommendation','')}</td>
          </tr>"""
        unm_html = f"""
      <div class="asmnt-section-label">3 · Módulos sin Mantenimiento</div>
      <table class="asmnt-table">
        <thead><tr>
          <th>Módulo</th><th>Función</th><th>Riesgo</th>
          <th>Reemplazo</th><th>Esfuerzo</th><th>Recomendación</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>"""

    # ── Effort summary ────────────────────────────────────────────────────
    c_lo  = effort.get("core_min", 0)
    c_hi  = effort.get("core_max", 0)
    cu_lo = effort.get("custom_min", 0)
    cu_hi = effort.get("custom_max", 0)
    u_lo  = effort.get("unmaintained_min", 0)
    u_hi  = effort.get("unmaintained_max", 0)
    t_lo  = effort.get("total_min", 0)
    t_hi  = effort.get("total_max", 0)

    effort_html = f"""
      <div class="asmnt-section-label" style="margin-top:24px">Esfuerzo Total Estimado</div>
      <div class="asmnt-effort-box">
        <div class="asmnt-stat">
          <div class="asmnt-stat-val">{_fmt_effort_range(c_lo, c_hi)}</div>
          <div class="asmnt-stat-lbl">días · Core</div>
        </div>
        <div class="asmnt-stat">
          <div class="asmnt-stat-val">{_fmt_effort_range(cu_lo, cu_hi)}</div>
          <div class="asmnt-stat-lbl">días · Módulos custom</div>
        </div>
        <div class="asmnt-stat">
          <div class="asmnt-stat-val">{_fmt_effort_range(u_lo, u_hi)}</div>
          <div class="asmnt-stat-lbl">días · Sin mantenimiento</div>
        </div>
        <div class="asmnt-stat asmnt-stat-total">
          <div class="asmnt-stat-val-total">{_fmt_effort_range(t_lo, t_hi)}</div>
          <div class="asmnt-stat-lbl">días · Total</div>
        </div>
      </div>
      <p class="asmnt-note">
        * Días de desarrollo para un desarrollador Etendo con experiencia.
        Rango bajo = módulo oficial de reemplazo disponible. Rango alto = desarrollo desde cero.
      </p>"""

    return f"""
  <div class="card">
    <h2>🔬 Análisis de Customizaciones</h2>
    <p class="asmnt-meta">
      Generado por <strong>etendo-custom-assessor v{assessment.get('assessor_version','1.0')}</strong>
      · {generated}
    </p>
    {core_html}
    {custom_html}
    {unm_html}
    {effort_html}
  </div>"""


# ── main render ───────────────────────────────────────────────────────────────

def render(report):
    client     = report.get("client", {})
    platform   = report.get("platform", {})
    score      = report.get("migration_score", 0)
    label      = report.get("migratability", "")
    breakdown  = report.get("score_breakdown", {})
    modules    = report.get("modules", {})
    core       = report.get("core_divergences", {})
    assessment = report.get("custom_assessment")

    total_modules = sum(len(v) for v in modules.values())
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")

    pills_html = ""
    for cat in ("gradle_jar", "gradle_source", "local_maintained", "local_not_maintained", "custom"):
        color     = category_color(cat)
        icon      = category_icon(cat)
        label_cat = category_label(cat)
        cnt       = len(modules.get(cat, []))
        pills_html += f"""
      <div class="module-pill">
        <div class="pill-icon" style="color:{color}">{icon}</div>
        <div class="pill-info">
          <strong style="color:{color}">{cnt}</strong>
          <span>{label_cat}</span>
        </div>
      </div>"""

    core_version = core.get("base_version") or "—"
    inst_version = platform.get("version") or "—"

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Etendo Migration Report — {client.get('name', '')}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="page">

  <div class="report-header">
    <h1>Etendo Migration Report</h1>
    <div class="sub">Análisis de migración a SaaS</div>
    <div class="header-meta">
      <div class="meta-item"><span>Cliente </span><strong>{client.get('name', '—')}</strong></div>
      <div class="meta-item"><span>Hostname </span><strong>{client.get('hostname', '—')}</strong></div>
      <div class="meta-item"><span>Plataforma </span><strong>{platform.get('type', '—').capitalize()} {inst_version}</strong></div>
      <div class="meta-item"><span>Base de comparación </span><strong>v{core_version}</strong></div>
      <div class="meta-item"><span>Módulos totales </span><strong>{total_modules}</strong></div>
      <div class="meta-item"><span>Generado </span><strong>{generated}</strong></div>
    </div>
  </div>

  <div class="card">
    <h2>Metodología de puntuación</h2>
    {render_methodology()}
  </div>

  <div class="card">
    <h2>Puntuación de migración</h2>
    <div class="score-section">
      {render_score_ring(score, report.get('migratability', ''))}
      <div class="score-right">
        <p style="font-size:13px;color:#475569;margin-bottom:12px;">Factores de penalización:</p>
        {render_breakdown(breakdown, score)}
      </div>
    </div>
  </div>

  <div class="card">
    <h2>Módulos ({total_modules})</h2>
    <div class="module-pills">{pills_html}</div>
    {render_modules(modules)}
  </div>

  <div class="card">
    <h2>Divergencias en core (vs v{core_version})</h2>
    {render_core(core)}
  </div>

  {render_assessment(assessment) if assessment else ""}

  <div class="footer">Generado por Etendo Migration Agent · {generated}</div>
</div>
<script>{JS}</script>
</body>
</html>"""
    return html


def main():
    args = parse_args()
    with open(args.input) as f:
        report = json.load(f)
    html = render(report)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"HTML report saved to: {output_path}")


if __name__ == "__main__":
    main()
