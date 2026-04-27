---
description: "Cross-client portfolio analysis: UI feature roadmap by client spread, unmaintained module maintenance candidates, and generalizable core customizations. Appends analysis sections to the dashboard."
argument-hint: ""
---

# etendo-portfolio-analysis

**Arguments:** none (analyzes all reports in `reports/` that have `custom_assessment` and/or `ui_readiness`)

You are an Etendo migration strategist. Your job is to analyze the full client portfolio by cross-referencing all available per-client assessments and produce three strategic sections appended to the dashboard HTML.

**Important:** The canonical implementation for the portfolio sections lives in `scripts/portfolio_analysis.py`. When invoked as a skill, first run the Mixpanel status check (Step 0 below), then run that script:

```python
import subprocess, sys
from pathlib import Path

result = subprocess.run(
    [sys.executable, "scripts/portfolio_analysis.py"],
    cwd=Path("reports").parent,
    capture_output=True, text=True
)
print(result.stdout)
if result.returncode != 0:
    print("ERROR:", result.stderr)
```

If you need to debug or extend the analysis, read `scripts/portfolio_analysis.py` first to understand the current implementation before making any changes. The steps below describe the full logic as documentation.

---

## Step 0 — Check Mixpanel coverage for all clients (MCP)

Before running the portfolio analysis, query Mixpanel to determine which clients are sending usage data. This updates `reports/mixpanel_status.json`, which `dashboard.py` reads to populate the "Mixpanel" column in the client table.

**The Mixpanel project is shared** — all Etendo clients send events to project ID `3851637` ("Etendo") and are differentiated by the event property `source_instance`.

```python
# 1. Get all source_instance values from Mixpanel using Run-Query
#    (Run-Query with breakdown is more reliable than Get-Property-Values,
#     which only returns "prominent" high-frequency values and misses low-activity clients)
#
# Use: mcp__claude_ai_Mixpanel_EU__Run-Query
#   project_id=3851637
#   query: Insights query — count of "Window Operation" events in last 7 days,
#          breakdown by source_instance
#
# Example query structure (adjust dates dynamically to yesterday - 7 days ago):
#   {
#     "type": "insights",
#     "bookmark": { "sections": {
#       "show": [{"math": "total", "type": "event", "value": "Window Operation"}],
#       "filter": [],
#       "group_by": [{"type": "event", "value": "source_instance"}],
#       "time": [{"type": "in the last", "unit": "day", "value": 7}]
#     }}
#   }
#
# Extract all source_instance values from the result rows:
#   mixpanel_instances = [row["value"] for row in result["data"]["values"]
#                         if row.get("value")]
#
# 2. For each client JSON in reports/, match slug/name against source_instance values
#    Normalize both sides: lowercase, strip non-alphanumeric
#    Skip UUIDs and internal instances (demo25, demo24, futit-staff, mirovi)
#
# 3. Save results to reports/mixpanel_status.json:
import json, re
from pathlib import Path
from datetime import date

mixpanel_instances = [...]  # values from MCP call above

def normalize(s):
    return re.sub(r'[^a-z0-9]', '', s.lower())

norm_instances = [normalize(i) for i in mixpanel_instances]
status = {}

for path in sorted(Path("reports").glob("*.json")):
    if path.stem in ("ranking", "portfolio_analysis", "mixpanel_status"):
        continue
    try:
        r = json.loads(path.read_text())
    except Exception:
        continue
    if "migration_score" not in r:
        continue

    slug = path.stem
    client_name = r.get("client", {}).get("name", slug)
    slug_norm = normalize(slug)
    name_norm = normalize(client_name)

    matched_instance = None
    for raw, norm in zip(mixpanel_instances, norm_instances):
        if re.match(r'^[0-9a-f-]{36}$', raw) or raw in ("demo25","demo24","futit-staff","mirovi"):
            continue
        if slug_norm in norm or norm in slug_norm or name_norm in norm or norm in name_norm:
            matched_instance = raw
            break

    status[slug] = {
        "client_name": client_name,
        "has_mixpanel": matched_instance is not None,
        "source_instance": matched_instance,
    }

Path("reports/mixpanel_status.json").write_text(
    json.dumps({"generated": date.today().isoformat(), "clients": status}, indent=2, ensure_ascii=False)
)
print(f"✓ {sum(1 for v in status.values() if v['has_mixpanel'])}/{len(status)} clients with Mixpanel data")
```

### Manual slug → source_instance overrides

Some clients use a `source_instance` that doesn't match their slug or report name automatically. **Always apply these overrides** after the auto-matching step, before writing `mixpanel_status.json`:

```python
MANUAL_MIXPANEL_OVERRIDES = {
    # slug          : exact source_instance value in Mixpanel
    "mdf"           : "MDF",
    "ole"           : "Ole Comunicación",
    "flexellon"     : "Flexellon",
    "nexe"          : "Nexe the way of change Iberia",
    "bed4u"         : "Bed4U",
    "bercaber"      : "Bercaber",
    "ccsa"          : "Cerveceria Cubana",
    "supermix"      : "MyPime Supermix Pucara",
    "mipyme"        : "MyPime Hercam",
    "pazo_pondal_s_l": "Pazo Pondal S.L.",
}

for slug, source_instance in MANUAL_MIXPANEL_OVERRIDES.items():
    if slug in status:
        status[slug]["has_mixpanel"] = True
        status[slug]["source_instance"] = source_instance
```

> If the user reports a new mapping (e.g. "client X appears in Mixpanel as Y"), add it here so it persists across runs.

After saving `mixpanel_status.json`, run `python3 scripts/portfolio_analysis.py` and then `python3 dashboard.py` to regenerate the dashboard with the updated Mixpanel column.

---

## Three sections produced

1. **Preparación para nueva UI — Roadmap por funcionalidad**
   Aggregates UI features across ALL clients and ranks them by how many clients need them (feature-first, not client-first). The goal is to drive the Etendo UI roadmap: a feature that is critical for 3 clients is more urgent than one critical for only 1.

2. **Módulos sin mantenimiento — candidatos a soporte oficial**
   Identifies unmaintained modules that appear across multiple clients or are high-risk without replacement. These are candidates for Etendo to take over or publish as official bundles.

3. **Customizaciones generalizables**
   Surfaces core modifications proposed for upstream and custom modules that could become official marketplace bundles, with estimated effort savings for the portfolio.

---

## Step 1 — Discover analyzed reports

Scan `reports/` for all JSON files that have `custom_assessment` and/or `ui_readiness`:

```python
import json
from pathlib import Path

reports_dir = Path("reports")
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
            "ui_readiness": r.get("ui_readiness") if has_ui else None,
            "custom_assessment": r.get("custom_assessment") if has_ca else None,
        })

print(f"Found {len(analyzed)} analyzed reports: {[a['slug'] for a in analyzed]}")
```

---

## Step 2 — UI feature roadmap (feature-first, not client-first)

The key insight: instead of ranking clients by their UI score, aggregate **per feature** across all clients. For each feature section (e.g., "6" = Callouts, "4" = Display Logic), collect:
- Which clients have it as `critica` / `alta` / `media` / `no_aplica`
- The `portfolio_score` = sum of weighted client priorities: critica×4, alta×2, media×1

This drives the roadmap: features affecting many clients with high priority should be implemented first.

```python
from analyzer.ui_scorer import enrich_ui_readiness

PRIORITY_WEIGHT = {"critica": 4, "alta": 2, "media": 1, "no_aplica": 0}

feature_map = {}
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
        # Worst (lowest) completion_pct across clients
        if f.get("completion_pct", 0) < entry["completion_pct"] or entry["completion_pct"] == 0:
            entry["completion_pct"] = f.get("completion_pct", 0)

# Compute portfolio_score and build final list
feature_roadmap = []
for section, data in feature_map.items():
    cbp = data["clients_by_priority"]
    portfolio_score = sum(PRIORITY_WEIGHT.get(p, 0) * len(c) for p, c in cbp.items())
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
        "total_affected": affected,
        "avg_ad_count": avg_ad,
        "portfolio_score": portfolio_score,
    })

# Sort: highest portfolio_score first, then least-done first
feature_roadmap.sort(key=lambda x: (-x["portfolio_score"], x["completion_pct"]))
```

**Roadmap priority labels** (used in the HTML):
- **P1 — Inmediata**: feature is `critica` in ≥2 client environments
- **P2 — Alta**: `critica` in exactly 1 client with high portfolio impact (score ≥4)
- **P3 — Media**: `alta` in several but not critical anywhere
- **P4 — Baja**: low overall impact

---

## Step 3 — Unmaintained module analysis

Collect all `unmaintained_modules` across clients, normalize locale suffixes
(e.g. `com.smf.shopify.es_es` → `com.smf.shopify`), and compute:
- `priority_score` = `client_count × risk_weight` (high=3, medium=2, low=1)
- Split into `etendo_candidates` (multi-client OR high-risk + no replacement) and `replaceable`

Sort by `priority_score` descending.

---

## Step 4 — Generalizable customizations

Collect:
- `core_customizations` with `conclusion=upstream` → propose to Etendo core team
- `custom_modules` with `generalization=bundle_candidate` → propose as marketplace module
- `unmaintained_modules` with `generalization=bundle_candidate` and no replacement that are not already in `etendo_candidates`

Group core upstream items by name (same customization appearing in multiple clients gets merged into one row).

---

## Step 5 — Save portfolio_analysis.json

```python
import json
from datetime import date

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

Path("reports/portfolio_analysis.json").write_text(
    json.dumps(portfolio, indent=2, ensure_ascii=False)
)
```

---

## Step 6 — Generate HTML and inject into dashboard

Inject three sections before `</body>`. Use `<!-- PORTFOLIO_ANALYSIS -->` / `<!-- /PORTFOLIO_ANALYSIS -->` markers for idempotency (replace on re-run).

### Section 1: Preparación para nueva UI — Roadmap por funcionalidad

Table columns: **Funcionalidad** | **Prioridad roadmap** | **Crítica · Alta · Media / N entornos** | **Entornos afectados** | **Avance UI** | **AD promedio**

- **Prioridad roadmap**: P1 badge (red) if `len(clients_critica) >= 2`, P2 (orange) if critica=1 + score≥4, P3 (yellow) if score≥4, P4 (grey) otherwise
- **Entornos afectados**: show client name as colored pill — red bg for critica, orange for alta, yellow for media
- **Avance UI**: progress bar based on `completion_pct`
- Skip features where `total_affected == 0`
- Above the table: compact badges showing each client's UI score
- Below the table: legend explaining the pill colors

### Section 2: Módulos sin mantenimiento — candidatos a soporte oficial

Two subsections:
- **2a**: `etendo_candidates` table — Módulo | Función | Clientes | Riesgo | ¿Reemplazo? | Esfuerzo promedio
- **2b**: `replaceable` compact table — Módulo | Clientes | Reemplazo oficial | Riesgo

### Section 3: Customizaciones generalizables

Two subsections:
- **3a**: Core upstream candidates — Customización | Cliente(s) | Descripción | Justificación | Esfuerzo SaaS
- **3b**: Bundle candidates — Módulo | Cliente | Funcionalidad | Complejidad/Riesgo | Esfuerzo SaaS

---

## Important notes

- **Always run `scripts/portfolio_analysis.py` directly** rather than reimplementing the logic inline — the script is the source of truth.
- Do NOT regenerate the dashboard from scratch. Only inject/replace the portfolio sections.
- Use `<!-- PORTFOLIO_ANALYSIS -->` / `<!-- /PORTFOLIO_ANALYSIS -->` markers for idempotent injection.
- All text in Spanish (consistent with the rest of the dashboard).
