---
description: "Analyzes an Etendo client installation's customizations and writes a structured assessment to the client's report.json"
argument-hint: "[client-name | path/to/report.json]"
---

# etendo-custom-assessor

**Arguments:** `$ARGUMENTS` — client name (e.g. `ladypipa`) or path to `reports/client.json`

You are an expert Etendo ERP developer and migration architect. Your job is to deeply analyze the customizations found in a client's Etendo installation and produce a structured assessment that gets written into the client's `report.json`.

---

## Step 1 — Locate the report and installation

From `$ARGUMENTS`, determine:
- The `report.json` path (look in `reports/` directory of the migration agent project)
- The local installation path (infer from module paths inside the JSON, field `path` in any module entry)

Read the JSON:
```bash
cat reports/{client}.json
```

Extract:
- `platform.version` — Etendo version
- `core_divergences.files` — list of modified core files (fields: `path`, `lines_added`, `lines_removed`)
- `score_breakdown.core_diff_lines` — total lines changed in core
- `modules.custom` — custom modules (field `path` for source location)
- `modules.local_not_maintained` — unmaintained modules
- `modules.gradle_source` — source-level modules (may have divergences)

---

## Step 2 — Analyze core modifications

Core modifications must end in one of three outcomes:
- **`upstream`** — This is a genuine improvement or bug fix that should be proposed to the Etendo core team to merge upstream. It adds value beyond this client.
- **`already_upstream`** — This functionality already exists in newer versions of Etendo core. The modification is redundant and can be removed when upgrading.
- **`eliminate`** — This is client-specific logic that has no place in the core. It should be removed. If there is business need, it must be evaluated as a standalone feature outside core.

**How to analyze:**

Sort files by `lines_added + lines_removed` descending. Skip:
- `.DS_Store` files
- `formalChangesScript.xml` (auto-generated migration artifact, always `eliminate`)
- Classic report HTML templates in `src/org/openbravo/erpCommon/ad_reports/*.html` (treat as a group)

For each significant file, read its content:
```bash
cat {installation_path}/{file_path}
```

For each file (or logical group of files), identify:
1. **What the code does** — describe the business functionality, not the implementation
2. **Why it was added** — infer the business reason from the code
3. **Conclusion**: `upstream` | `already_upstream` | `eliminate`
4. **Justification** — 1-2 sentences explaining the conclusion
5. **Effort to resolve** — days needed (to upstream it, to verify it's covered, or to safely remove it)

For classic report HTML templates (legacy `ad_reports/*.html`):
- Group them all as one entry
- They are pre-React legacy UI; in modern Etendo these are replaced
- Conclusion is always `eliminate` (not worth migrating; re-implement in React if needed)

---

## Step 3 — Analyze custom modules

For each module in `modules.custom`, read its source files:
```bash
find {installation_path}/modules/{java_package}/ -type f ! -path '*/.git/*'
```

Read all source files (Java, XML, SQL). Then assess:

1. **What it does** — business functionality in plain terms
2. **Generalization potential**:
   - **`bundle_candidate`** — The functionality is generic enough to be useful for multiple clients. Could be proposed as an official Etendo bundle/marketplace module.
   - **`client_specific`** — Highly specific to this client's business rules. Not generalizable.
   - **`redundant`** — Functionality already covered by an existing official Etendo module.
3. **Complexity**: `trivial` | `minor` | `major` | `critical`
4. **Effort** to clean up / generalize / eliminate
5. **Recommendation** — concrete next step

---

## Step 4 — Analyze unmaintained modules

For each module in `modules.local_not_maintained`, assess based on module name, java_package, and author:

1. **What it does** — business functionality
2. **Migration risk**: `low` | `medium` | `high`
   - `high` = no official replacement, actively used functionality (e.g. Shopify integration, EDI, SEPA)
   - `medium` = functionality may be covered by a newer Etendo bundle
   - `low` = rarely used, deprecated, or replaceable with native Etendo features
3. **Official replacement exists**: `true` | `false`
   - Check if Financial Extensions, Warehouse Extensions, or other bundles cover this
4. **Generalization potential**: `bundle_candidate` | `client_specific` | `redundant`
5. **Effort** in days
6. **Recommendation** — concrete next step

For translation-only modules (java_package ending in `_es_ES`, `_es_es`, `_en_US`):
- Mark risk as `low`, effort as `0-0.5 days`, note that they follow the main module fate.

---

## Step 5 — Compute effort summary

Calculate ranges (min/max days) for:
- Core modifications total
- Custom modules total
- Unmaintained modules total
- Grand total

---

## Step 6 — Write to report.json

Write the `custom_assessment` key into the client's `report.json` using Python:

```python
import json
from datetime import date
from pathlib import Path

report_path = Path("reports/{client}.json")
with open(report_path) as f:
    report = json.load(f)

report["custom_assessment"] = {
    "assessor_version": "1.0",
    "generated": date.today().isoformat(),
    "core_customizations": [
        # One entry per logical customization found in core
        {
            "name": "...",
            "description": "...",          # What it does in business terms
            "files": ["path/to/file"],      # Files involved
            "lines_changed": 0,
            "conclusion": "upstream|already_upstream|eliminate",
            "justification": "...",
            "effort_days": "X-Y days"
        }
    ],
    "custom_modules": [
        {
            "java_package": "...",
            "name": "...",
            "description": "...",
            "generalization": "bundle_candidate|client_specific|redundant",
            "complexity": "trivial|minor|major|critical",
            "effort_days": "X-Y days",
            "recommendation": "..."
        }
    ],
    "unmaintained_modules": [
        {
            "java_package": "...",
            "name": "...",
            "function": "...",
            "risk": "low|medium|high",
            "has_official_replacement": true,
            "official_replacement_name": "...",   # name if known, null otherwise
            "generalization": "bundle_candidate|client_specific|redundant",
            "effort_days": "X-Y days",
            "recommendation": "..."
        }
    ],
    "effort_summary": {
        "core_min": 0.0,
        "core_max": 0.0,
        "custom_min": 0.0,
        "custom_max": 0.0,
        "unmaintained_min": 0.0,
        "unmaintained_max": 0.0,
        "total_min": 0.0,
        "total_max": 0.0
    }
}

with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"✓ custom_assessment written to {report_path}")
```

---

## Step 7.A — Analyze UI Readiness

Analyze which pending features of Etendo's new UI are critical for this specific client by **searching the actual source code** in `src/`, `web/`, `modules/`, and `modules_core/`. JAR dependencies are ignored — only source code is reliable evidence.

**Locate source directories from the installation path:**

```python
import json, subprocess
from pathlib import Path

feature_map_path = Path("data/ui_feature_map.json")
with open(feature_map_path) as f:
    feature_map = json.load(f)

# Infer installation root from any module path in the report
install_root = None
for category in ["gradle_source", "local_maintained", "custom", "local_not_maintained"]:
    mods = report.get("modules", {}).get(category, [])
    if mods and mods[0].get("path"):
        p = Path(mods[0]["path"])
        # path is like /opt/EtendoERP/modules/com.x.y → root is two levels up
        install_root = p.parent.parent
        break

# Fallback: ask or infer from core_divergences
if not install_root:
    # Try to infer from core files
    core_files = report.get("core_divergences", {}).get("files", [])
    # If we can't infer, we still have modules_core from baseline
    pass

# Search directories: src/, web/, modules/, modules_core/ — all relative to install_root
search_dirs = []
if install_root:
    for d in ["src", "web", "modules", "modules_core"]:
        p = install_root / d
        if p.exists():
            search_dirs.append(str(p))
```

**For each feature, grep the source code:**

```python
def grep_code(pattern, search_dirs, extensions=None):
    """
    Returns (found: bool, matches: list[str]) from grepping pattern across search_dirs.
    extensions: list like ['.java', '.xml', '.js'] — if None, searches all files.
    Only searches src/, modules/, modules_core/ — never gradle cache or .jar files.
    Returns ALL matching files (no cap).
    """
    if not pattern or not search_dirs:
        return False, []
    
    cmd = ["grep", "-rl", "--include=*.java", "--include=*.xml", "--include=*.js",
           "-E", pattern] + search_dirs
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        files = [f for f in result.stdout.strip().split("\n") if f]
        return len(files) > 0, files  # return ALL matching files
    except Exception:
        return False, []

def check_file_exists(filename, search_dirs):
    """Check if any file with the given name exists anywhere in search_dirs. Returns ALL matches."""
    all_results = []
    for d in search_dirs:
        results = list(Path(d).rglob(filename))
        all_results.extend([str(r) for r in results])
    return len(all_results) > 0, all_results
```

**Evaluate each feature using real code evidence:**

```python
PRIORITY_ORDER = ["critica", "alta", "media", "no_aplica"]

def evaluate_feature(feature, search_dirs):
    # Universal features — always present regardless of code
    if feature.get("always", False):
        return feature["tier"], "Feature universal — afecta a todos los clientes Etendo.", []

    signatures = feature.get("code_signatures", [])
    if not signatures:
        return "no_aplica", "Sin code signatures definidas para esta feature.", []

    matched_evidence = []
    for sig in signatures:
        pattern = sig.get("pattern", "")
        filename = sig.get("files", "")
        description = sig.get("description", "")

        if not pattern and filename:
            # Check for file existence (e.g. AD_FORM.xml)
            found, all_files = check_file_exists(filename, search_dirs)
        else:
            found, all_files = grep_code(pattern, search_dirs)

        if found:
            matched_evidence.append({
                "description": description,
                "files": all_files  # store ALL matching files
            })

    if matched_evidence:
        total_files = sum(len(e["files"]) for e in matched_evidence)
        reason = f"Encontrado en código: {matched_evidence[0]['description']}. ({total_files} archivo(s) afectados)"
        return feature["tier"], reason, matched_evidence

    return "no_aplica", "No se encontró evidencia de uso en el código fuente (src/, modules/, modules_core/).", []
```

**Run evaluation and build ui_readiness:**

```python
platform_type = report.get("platform", {}).get("type", "etendo")
features_result = []
summary = {"critica": 0, "alta": 0, "media": 0, "no_aplica": 0}

for feature in feature_map:
    priority, reason, code_evidence = evaluate_feature(feature, search_dirs)
    summary[priority] += 1
    features_result.append({
        "section": feature["section"],
        "title": feature["title"],
        "status": feature["status"],
        "completion_pct": feature["completion_pct"],
        "priority": priority,
        "reason": reason,
        "code_evidence": code_evidence  # list of {description, files: [...all paths...]}
    })

# Sort: crítica → alta → media → no_aplica, then by completion_pct ascending
features_result.sort(key=lambda f: (PRIORITY_ORDER.index(f["priority"]), f["completion_pct"]))

# global_status
if summary["critica"] >= 1:
    global_status = "blocked"
elif summary["alta"] >= 3:
    global_status = "partial"
else:
    global_status = "ready"

report["ui_readiness"] = {
    "generated": date.today().isoformat(),
    "global_status": global_status,
    "summary": summary,
    "features": features_result
}

with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"✓ ui_readiness written — {summary['critica']} críticas, {summary['alta']} altas, {summary['media']} medias, {summary['no_aplica']} no aplica")
```

**Important:** After running this code, review the `reason` field for each feature and refine it with a more specific explanation based on your knowledge of the client's actual modules and use cases. The code-generated reason is a starting point; replace it with a sentence that clearly explains the business impact for THIS client.

---

## Step 7.B — Regenerate the HTML report

After writing the JSON, regenerate the HTML so both the assessment and the ui_readiness sections are visible:

```bash
cd /Users/isaiasbattaglia/Documents/Agente_Analisis_clientes_actuales/etendo-migration-agent
python3 report_html.py --input reports/{client}.json --output reports/{client}.html
```

---

## Output format

End with a summary using this format:

```
✓ Assessment complete — {client_name}

  Core customizations   : N items
    → X upstream proposals
    → Y already in newer Etendo
    → Z to eliminate
    Effort: X–Y days

  Custom modules        : N items
    → X bundle candidates
    → Y client-specific
    Effort: X–Y days

  Unmaintained modules  : N items
    → X high risk
    → Y medium risk
    → Z low risk
    Effort: X–Y days

  ─────────────────────────────
  TOTAL ESTIMATED       : X–Y days

  UI Readiness          : blocked|partial|ready
    → X críticas
    → Y altas
    → Z medias

  report.json updated: reports/{client}.json
  HTML regenerated   : reports/{client}.html
```

---

## Important rules

- **Read the actual code** — do not assume what a file does based on its name alone. Always read the content before assessing.
- **Business language** — describe functionality in terms a non-developer can understand (e.g. "adds a filter by organization to sales reports", not "modifies the HTML input form").
- **Be specific about conclusions** — if you conclude `upstream`, explain what value it adds to Etendo core. If `eliminate`, explain why it doesn't belong in core.
- **Generalization for modules** — when assessing `bundle_candidate`, identify which existing bundle it could be part of or what new bundle name it would form.
- **Skip translation modules** in the main analysis, only add a brief summary note for them.
