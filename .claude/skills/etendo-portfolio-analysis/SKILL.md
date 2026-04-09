---
description: "Cross-client portfolio analysis: UI readiness ranking, unmaintained module maintenance candidates, and generalizable core customizations. Appends analysis sections to the dashboard."
argument-hint: ""
---

# etendo-portfolio-analysis

**Arguments:** none (analyzes all reports in `reports/` that have `custom_assessment` and/or `ui_readiness`)

You are an Etendo migration strategist. Your job is to analyze the full client portfolio by cross-referencing all available per-client assessments and produce three strategic sections that get appended to the dashboard HTML:

1. **Preparación para nueva UI** — ranks clients by `ui_migration_score` and summarizes the critical blockers per client.
2. **Módulos a mantener por Etendo** — identifies unmaintained modules that appear across multiple clients and should be taken over or officially supported by Etendo.
3. **Customizaciones generalizables** — identifies core and module customizations marked `upstream` or `bundle_candidate` across clients and makes a case for investing in them.

---

## Step 1 — Discover analyzed reports

Scan `reports/` for all JSON files. For each, check which sections are present:

```python
import json
from pathlib import Path

reports_dir = Path("reports")
analyzed = []

for path in sorted(reports_dir.glob("*.json")):
    if path.stem in ("ranking",):  # skip meta-files
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

print(f"Found {len(analyzed)} analyzed reports: {[a['slug'] for a in analyzed]}")
```

Print the list so you know which clients you are working with.

---

## Step 2 — UI Readiness ranking

From clients that have `ui_readiness`, compute the ranking:

```python
from analyzer.ui_scorer import enrich_ui_readiness

ui_clients = []
for a in analyzed:
    if not a["ui_readiness"]:
        continue
    ui = a["ui_readiness"]
    # Ensure score is computed
    if ui.get("ui_migration_score") is None:
        enrich_ui_readiness(ui)
    ui_clients.append({
        "slug": a["slug"],
        "name": a["name"],
        "ui_score": ui.get("ui_migration_score", 0),
        "ui_label": ui.get("ui_label", ""),
        "global_status": ui.get("global_status", ""),
        "summary": ui.get("summary", {}),
        "critical_features": [
            f for f in ui.get("features", [])
            if f.get("priority") == "critica" and f.get("completion_pct", 100) < 60
        ],
    })

ui_clients.sort(key=lambda x: x["ui_score"], reverse=True)
```

For each client, identify the **top 3 critical blockers** (features with `priority=critica` and lowest `completion_pct`). These become the summary shown in the dashboard.

---

## Step 3 — Unmaintained module analysis

Collect all `unmaintained_modules` across all clients:

```python
from collections import defaultdict

module_map = defaultdict(lambda: {
    "clients": [],
    "risk_levels": [],
    "has_replacement": None,
    "official_replacement_name": None,
    "generalization": None,
    "effort_update_hours_avg": [],
    "effort_saas_hours_avg": [],
    "name": "",
    "function": "",
    "api_changes": set(),
})

for a in analyzed:
    if not a["custom_assessment"]:
        continue
    for m in a["custom_assessment"].get("unmaintained_modules", []):
        pkg = m.get("java_package", "")
        # Normalize: strip locale suffix for grouping (e.g. com.smf.shopify.es_es → com.smf.shopify)
        import re
        base_pkg = re.sub(r'[._][a-z]{2}[._][a-zA-Z]{2}$', '', pkg)
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

# Compute priority score: clients_count × risk_weight (high=3, medium=2, low=1)
RISK_W = {"high": 3, "medium": 2, "low": 1}

module_candidates = []
for pkg, data in module_map.items():
    # Skip translation packs (their base pkg already merged above)
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

# Sort: multi-client first, then by risk, then by name
module_candidates.sort(key=lambda x: (-x["priority_score"], -x["client_count"], x["java_package"]))

# Split into: needs Etendo maintenance (multi-client OR high-risk, no replacement) vs has replacement
etendo_candidates = [m for m in module_candidates if m["client_count"] >= 2 or (m["max_risk"] == "high" and not m["has_replacement"])]
replaceable = [m for m in module_candidates if m not in etendo_candidates and m["has_replacement"]]

print(f"Etendo maintenance candidates: {len(etendo_candidates)}")
print(f"Has replacement: {len(replaceable)}")
```

---

## Step 4 — Generalizable customizations

Collect all `core_customizations` and `custom_modules` across clients:

```python
generalizable = []

for a in analyzed:
    if not a["custom_assessment"]:
        continue
    client_name = a["name"]
    # Core customizations proposed for upstream
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
    # Custom modules that are bundle candidates
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
    # Unmaintained modules that are bundle candidates (single-client, not in etendo_candidates yet)
    for m in a["custom_assessment"].get("unmaintained_modules", []):
        if m.get("generalization") == "bundle_candidate" and not m.get("has_official_replacement"):
            import re
            base_pkg = re.sub(r'[._][a-z]{2}[._][a-zA-Z]{2}$', '', m.get("java_package", ""))
            # Only add if not already in etendo_candidates
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

# Group core upstreams by name (same customization in multiple clients)
from collections import defaultdict
upstream_groups = defaultdict(list)
for g in generalizable:
    if g["type"] == "core":
        upstream_groups[g["name"]].append(g)

print(f"Generalizable items: {len(generalizable)} ({len(upstream_groups)} unique core upstreams)")
```

---

## Step 5 — Write portfolio_analysis to a JSON file

Save the analysis to `reports/portfolio_analysis.json` for reference and future use:

```python
import json
from datetime import date
from pathlib import Path

portfolio = {
    "generated": date.today().isoformat(),
    "analyzed_clients": [a["slug"] for a in analyzed],
    "ui_readiness_ranking": [
        {
            "slug": c["slug"],
            "name": c["name"],
            "ui_score": c["ui_score"],
            "ui_label": c["ui_label"],
            "global_status": c["global_status"],
            "summary": c["summary"],
            "top_blockers": [
                {"section": f["section"], "title": f["title"], "completion_pct": f["completion_pct"], "ad_count": f.get("ad_count", 0)}
                for f in sorted(c["critical_features"], key=lambda x: x.get("completion_pct", 0))[:3]
            ],
        }
        for c in ui_clients
    ],
    "module_maintenance_candidates": etendo_candidates,
    "generalizable_customizations": generalizable,
}

Path("reports/portfolio_analysis.json").write_text(
    json.dumps(portfolio, indent=2, ensure_ascii=False)
)
print(f"✓ portfolio_analysis.json written")
```

---

## Step 6 — Generate HTML sections and append to dashboard

Read the current `reports/dashboard.html` and inject three new sections before the closing `</body>` tag.

**Read the current dashboard:**
```python
dashboard_path = Path("reports/dashboard.html")
html = dashboard_path.read_text()
```

**Build the three sections as HTML strings**, then inject them:

```python
# Find injection point — insert before </body>
inject_marker = "</body>"
new_sections = "\n".join([ui_section_html, modules_section_html, customizations_section_html])
html = html.replace(inject_marker, new_sections + "\n" + inject_marker)
dashboard_path.write_text(html)
print("✓ Dashboard updated with portfolio analysis sections")
```

### Section styles to use

These CSS classes are already available in the dashboard. Use them to stay visually consistent:

```
.section          — white card with padding and border-radius
.kpi-grid         — grid of metric cards
.kpi-card         — individual metric card with label + value
h2                — section heading
table, thead, tbody, tr, th, td  — standard table elements
.badge-easy / .badge-moderate / .badge-hard / .badge-very_hard  — score labels
```

Add a `<style>` block at the top of your injected HTML if you need additional styles. Keep them scoped with a prefix like `.portfolio-*`.

### Section 1: Preparación para nueva UI

Build a table ranking all clients with UI analysis:

| Cliente | UI Score | Estado | Críticas | Bloqueadores principales |
|---------|----------|--------|----------|--------------------------|

- **UI Score**: color-coded badge (same as dashboard: green ≥80, yellow ≥60, orange ≥40, red <40)
- **Estado**: `blocked` → rojo, `partial` → naranja, `ready` → verde
- **Bloqueadores**: list top 3 critical features with their `completion_pct` and `ad_count`, formatted as pills or small rows

Include a summary paragraph above the table explaining what the score means and the overall portfolio status.

### Section 2: Módulos sin mantenimiento — candidatos a soporte oficial

Build two subsections:

**2a. Candidatos a ser mantenidos por Etendo** (multi-client or high-risk without replacement):

| Módulo | Función | Clientes | Riesgo | ¿Reemplazo? | Esfuerzo promedio |
|--------|---------|---------|--------|-------------|-------------------|

- Highlight modules with `client_count >= 2` with a badge "N clientes"
- Mark `has_replacement=false` + `max_risk=high` with a red pill "Sin reemplazo"
- `avg_effort_update_hours` — show as "~Xh (actualización)"

**2b. Módulos con reemplazo oficial** (informational):
Compact list showing: module name → official replacement name.

Include a recommendation paragraph: which modules should Etendo prioritize taking over (ordered by `priority_score`).

### Section 3: Customizaciones generalizables

Build two subsections:

**3a. Modificaciones de core propuestas para upstream**:

| Customización | Cliente | Descripción | Justificación | Esfuerzo SaaS |
|---------------|---------|-------------|---------------|---------------|

Group entries that appear across multiple clients.

**3b. Módulos custom candidatos a bundle oficial**:

| Módulo | Cliente | Funcionalidad | Complejidad | Esfuerzo SaaS |
|--------|---------|--------------|-------------|---------------|

Include a paragraph explaining the strategic value: these are functionalities that, if maintained by Etendo or published as marketplace modules, would reduce the migration burden for all clients.

---

## Important notes

- Do NOT regenerate the dashboard from scratch. Only inject the new sections into the existing HTML.
- If the dashboard already contains a `<!-- PORTFOLIO_ANALYSIS -->` marker, replace everything between that marker and `<!-- /PORTFOLIO_ANALYSIS -->` instead of appending again.
- Wrap all injected content between `<!-- PORTFOLIO_ANALYSIS -->` and `<!-- /PORTFOLIO_ANALYSIS -->` markers.
- The sections go at the **very end of the page**, after all existing sections, before `</body>`.
- Use Spanish for all text labels, titles, and descriptions in the HTML (consistent with the rest of the dashboard).
- After writing the dashboard, print a summary of what was added.
