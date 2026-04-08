---
description: "Analyzes an Etendo client installation's customizations and writes a structured assessment to the client's report.json"
argument-hint: "[client-name | path/to/report.json]"
---

# etendo-custom-assessor

**Arguments:** `$ARGUMENTS` — client name (e.g. `ladypipa`) or path to `reports/client.json`

You are an expert Etendo ERP developer and migration architect with deep knowledge of the Application Dictionary (AD) model, Etendo's module system, and the status of the new React-based UI.

Your job is to deeply analyze the customizations found in a client's Etendo installation and produce a structured assessment that gets written into the client's `report.json`. The analysis is in two parts:
1. **Customization assessment** (Steps 1–6): evaluate core changes, custom modules, and unmaintained modules.
2. **UI Readiness** (Step 7.A): determine which features of the new Etendo UI are critical for this specific client by quantifying their actual use in the Application Dictionary.

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

## Step 5 — Fetch API changes and estimate effort

**Target version: Etendo 25.4.x** (latest Confirmed Stable).

### Sub-step 5.A — Fetch the API changelog

Fetch the API changes documentation and identify all breaking changes between the client's current version and 25.4.x:

```
WebFetch: https://docs.etendo.software/developer-guide/etendo-classic/developer-changelog/apichanges/
```

From the page, extract changes version by version starting from the client's `platform.version` up to 25.4.x. Focus on:
- Java API changes (deprecated/removed methods, class renames, interface changes)
- Database/PostgreSQL schema changes
- Library upgrades (Jackson, Hibernate, Spring, Guava, etc.)
- Gradle/build system changes
- Removed or replaced modules

### Sub-step 5.B — Identify which changes affect each module

For each module in `custom_modules` and `local_not_maintained`, cross-reference its source code with the API changes list. Specifically:
- Check which deprecated/removed APIs the module uses
- Check if any libraries it depends on changed
- For unmaintained modules: check if the module's last version predates critical breaking changes

### Sub-step 5.C — Estimate hours (single point, no ranges)

For each item, produce **two estimates in hours** (not days, not ranges):

**`effort_update_hours`** — Hours for a junior developer assisted by Claude Code to update the code to work with Etendo 25.4.x. Includes: fixing API breaks, updating deprecated calls, adapting to library changes, testing.

**`effort_saas_hours`** — Hours to eliminate, upstream, or generalize the customization as part of a SaaS migration. Includes: removing client-specific logic, writing documentation for upstreaming, or generalizing to a bundle candidate.

**Calibration guide (junior dev + Claude Code, not a senior working alone):**

| Task type | Hours |
|-----------|-------|
| Rename a deprecated class or method (find + replace) | 0.5 |
| Update a single service/API call to new signature | 1–2 |
| Adapt to a changed interface with behavioral difference | 3–6 |
| Rewrite a module subsystem for new architecture | 8–20 |
| Full module rewrite (unmaintained, no maintainer) | 20–60 |
| Verify if functionality is already in new version | 1 |
| Remove client-specific code cleanly (with testing) | 2–4 |
| Generalize to bundle candidate (refactor + docs) | 8–24 |
| Migrate config/data to official replacement module | 2–8 |
| Update translation pack (follows main module) | 0 |

**For unmaintained modules with no active maintainer:**
- `effort_update_hours` = hours to fork + update the module to work with 25.4.x
- If an official replacement exists: `effort_saas_hours` = hours to migrate data/config to it
- If no replacement: `effort_saas_hours` = hours to evaluate and decide (removal or rebuild)

**For core modifications:**
- `effort_update_hours` = hours to rebase the patch on 25.4.x core and verify it still applies
- `effort_saas_hours` = hours to remove/upstream/validate the patch is no longer needed

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
    "assessor_version": "2.0",
    "generated": date.today().isoformat(),
    "core_customizations": [
        # One entry per logical customization found in core
        {
            "name": "...",
            "description": "...",              # What it does in business terms
            "files": ["path/to/file"],         # Files involved
            "lines_changed": 0,
            "conclusion": "upstream|already_upstream|eliminate",
            "justification": "...",
            "api_changes_applicable": ["..."], # Which changelog entries affect this
            "effort_update_hours": 0,          # Hours to rebase patch on 25.4.x
            "effort_saas_hours": 0             # Hours to remove/upstream for SaaS
        }
    ],
    "custom_modules": [
        {
            "java_package": "...",
            "name": "...",
            "description": "...",
            "generalization": "bundle_candidate|client_specific|redundant",
            "complexity": "trivial|minor|major|critical",
            "api_changes_applicable": ["..."], # Which changelog entries affect this
            "effort_update_hours": 0,          # Hours to update module to 25.4.x
            "effort_saas_hours": 0,            # Hours to eliminate/generalize for SaaS
            "recommendation": "..."
        }
    ],
    "unmaintained_modules": [
        {
            "java_package": "...",
            "name": "...",
            "function": "...",
            "risk": "low|medium|high",
            "has_official_replacement": True,
            "official_replacement_name": "...",    # name if known, null otherwise
            "generalization": "bundle_candidate|client_specific|redundant",
            "api_changes_applicable": ["..."],     # Which changelog entries affect this
            "effort_update_hours": 0,              # Hours to fork + update to 25.4.x
            "effort_saas_hours": 0,                # Hours to migrate to replacement or remove
            "recommendation": "..."
        }
    ],
    "effort_summary": {
        # Ruta A: Actualización a Etendo 25.4.x (mantener instalación on-premise actualizada)
        "update_core_hours": 0,
        "update_custom_hours": 0,
        "update_unmaintained_hours": 0,
        "update_total_hours": 0,
        # Ruta B: Migración a SaaS (eliminar/generalizar customizaciones)
        "saas_core_hours": 0,
        "saas_custom_hours": 0,
        "saas_unmaintained_hours": 0,
        "saas_total_hours": 0
    }
}

with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"✓ custom_assessment written to {report_path}")
```

---

## Step 7.A — Analyze UI Readiness

Determine which features of Etendo's new React UI are critical for this specific client by analyzing their **Application Dictionary (AD) XML files**. The goal is to count how much the client actually uses each feature, then combine that with the completion status of the new UI to produce a concrete, quantified priority assessment.

**Reference:** Read `data/all-features.md` section by section as you work. It describes each feature's expected behavior, its checklist, and typical examples. Use it to understand context and draft specific `reason` fields — do NOT use `ui_feature_map.json`.

---

### Sub-step A1 — Locate AD XML directories

Infer the installation root from module paths in the report, then find all AD sourcedata directories:

```python
import json, subprocess, re
from pathlib import Path
from datetime import date

# Load report (already open from Step 6)
install_root = None
for category in ["gradle_source", "local_maintained", "custom", "local_not_maintained"]:
    mods = report.get("modules", {}).get(category, [])
    if mods and mods[0].get("path"):
        p = Path(mods[0]["path"])
        install_root = p.parent.parent  # /opt/EtendoERP/modules/com.x.y → /opt/EtendoERP
        break
```

```bash
# Find all AD sourcedata directories across core + installed modules
find {install_root} -type d -name "sourcedata" | grep "src-db/database" | sort
```

Store the list of `sourcedata_dirs`. These contain files like `AD_WINDOW.xml`, `AD_TAB.xml`, `AD_FIELD.xml`, `AD_COLUMN.xml`, `AD_PROCESS.xml`, `OBUIAPP_PROCESS.xml`, `AD_FORM.xml`, `OBUISEL_SELECTOR.xml`, etc.

---

### Sub-step A2 — Count AD instances per feature category

Run the following analyses. For each, use `grep -c` to count matching lines/entries, or `grep -l` to count files. Consolidate across ALL `sourcedata_dirs`.

**Helper:**
```python
def count_in_ad(pattern, sourcedata_dirs, filename_glob="*.xml"):
    """Count occurrences of pattern across all AD XML files. Returns (total_count, list_of_matching_files)."""
    total = 0
    matching = []
    for d in sourcedata_dirs:
        result = subprocess.run(
            ["grep", "-rl", "-E", pattern, d],
            capture_output=True, text=True, timeout=30
        )
        files = [f for f in result.stdout.strip().split("\n") if f and Path(f).name.endswith(".xml")]
        for f in files:
            r2 = subprocess.run(["grep", "-c", "-E", pattern, f], capture_output=True, text=True)
            try:
                total += int(r2.stdout.strip())
                matching.append(f)
            except ValueError:
                pass
    return total, matching
```

**Run these counts:**

```bash
# 1. Window Types — AD_WINDOW.xml
grep -rh "WINDOWTYPE=" {sourcedata_dirs} --include="AD_WINDOW.xml" | grep -oE 'WINDOWTYPE="[^"]+"' | sort | uniq -c
# Expected: M (Maintain), T (Transaction), Q (Query), OBUIAPP_PickAndExecute

# 2. Display Logic — fields with conditional visibility
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_FIELD.xml"    # count per module
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_COLUMN.xml"

# 3. Callouts — columns with server-side callout logic
grep -rc "<CALLOUT>" {sourcedata_dirs} --include="AD_COLUMN.xml"

# 4. Process Types — legacy vs modern
grep -rh "UIPATTERN=" {sourcedata_dirs} --include="AD_PROCESS.xml" | grep -oE 'UIPATTERN="[^"]+"' | sort | uniq -c
grep -rh "UIPATTERN=" {sourcedata_dirs} --include="OBUIAPP_PROCESS.xml" | grep -oE 'UIPATTERN="[^"]+"' | sort | uniq -c

# 5. Selectors (OBUISEL)
grep -rl "." {sourcedata_dirs} --include="OBUISEL_SELECTOR.xml" | wc -l   # modules with selectors
grep -rc "<OBUISEL_SELECTOR " {sourcedata_dirs} --include="OBUISEL_SELECTOR.xml"

# 6. Application Forms (AD_FORM)
grep -rl "." {sourcedata_dirs} --include="AD_FORM.xml" | wc -l
grep -rc "<AD_FORM " {sourcedata_dirs} --include="AD_FORM.xml"

# 7. Single-Record tabs
grep -rc 'UITYPE="SR"' {sourcedata_dirs} --include="AD_TAB.xml"

# 8. Read-only tabs
grep -rc 'ISREADONLY="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 9. Tab-level display logic (tab visibility)
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_TAB.xml"

# 10. Grid-initial tabs
grep -rc 'ISSHOWNINITIALGRIDMODE="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 11. Field Groups (collapsible sections)
grep -rc "AD_FIELDGROUP_ID=" {sourcedata_dirs} --include="AD_FIELD.xml"

# 12. Status Bar Fields
grep -rc 'ISSHOWNINSTATUSBAR="Y"' {sourcedata_dirs} --include="AD_FIELD.xml"

# 13. Hardcoded buttons (DocAction, Posted, CreateFrom, PaymentRule)
grep -rh "COLUMNNAME=" {sourcedata_dirs} --include="AD_COLUMN.xml" | grep -E 'COLUMNNAME="(DocAction|Posted|CreateFrom|PaymentRule|ChangeProjectStatus)"' | wc -l

# 14. Read-only logic (conditional editability)
grep -rc "READONLYLOGIC=" {sourcedata_dirs} --include="AD_COLUMN.xml"

# 15. Out-parameter selectors (populate multiple fields)
grep -rc 'ISOUTPARAMETER="Y"' {sourcedata_dirs} --include="OBUISEL_SELECTORFIELD.xml"

# 16. Default values with SQL or session vars
grep -rc "DEFAULTVALUE=" {sourcedata_dirs} --include="AD_COLUMN.xml"

# 17. Mandatory fields (form validation scale)
grep -rc 'ISMANDATORY="Y"' {sourcedata_dirs} --include="AD_COLUMN.xml"

# 18. Linked Items / KMO widgets
grep -rl "OBKMO\|LinkedItem\|WidgetClass" {sourcedata_dirs} --include="*.xml" | wc -l

# 19. Tree views
grep -rc 'HASTREE="Y"\|TREECATEGORY=' {sourcedata_dirs} --include="AD_TAB.xml"

# 20. Navigation menu size
grep -rc "<AD_MENU " {sourcedata_dirs} --include="AD_MENU.xml"
```

---

### Sub-step A3 — Assign priority per feature

For each feature section in `data/all-features.md`, decide the priority based on:

| Count in this client's AD | New UI status | Priority |
|--------------------------|---------------|----------|
| > 50 instances OR > 20 windows | NOT DONE / PARCIAL | **critica** |
| 10–50 instances OR 5–20 windows | NOT DONE / PARCIAL | **alta** |
| < 10 instances | NOT DONE / PARCIAL | **media** |
| 0 instances found | any | **no_aplica** |
| any count | DONE / TO CHECK | **media** or **no_aplica** |

**Etendo new UI completion status** (apply your knowledge as of training data):
- **DONE**: Basic CRUD (Maintain), Authentication, Navigation/Menu, Loading indicators
- **PARCIAL**: Transaction windows (Document State Machine incomplete), Selectors/out-params, Process Definitions
- **NOT DONE**: Callouts (OB.* namespace), Application Forms (AD_FORM), Classic Reports (legacy HTML), Tab-level display logic, Linked Items, Tree views, Widget/Dashboard

Use the counts from Sub-step A2 to write a specific `reason` for each feature (e.g. "Este cliente tiene 47 ventanas Transaction con máquina de estados — el botón DocAction y los estados Draft/Booked son críticos. El nuevo UI aún no tiene implementado el flujo completo de estado de documentos.").

---

### Sub-step A4 — Write ui_readiness to report.json

```python
PRIORITY_ORDER = ["critica", "alta", "media", "no_aplica"]

# Build features list from your analysis above
# One entry per logical feature section (not per XML file)
features_result = [
    # Example structure — fill in from your Sub-step A2/A3 analysis:
    {
        "section": "1.2",
        "title": "Transaction Windows (Document State Machine)",
        "status": "PARCIAL",
        "completion_pct": 40,
        "priority": "critica",   # or alta/media/no_aplica
        "reason": "Este cliente tiene N ventanas Transaction (pedidos, facturas, pagos). El flujo DocAction/estados aún no está completo en el nuevo UI.",
        "ad_count": 47,           # actual count from grep
        "code_evidence": []       # leave empty — evidence is the count above
    },
    # ... one entry per section from all-features.md
]

summary = {p: sum(1 for f in features_result if f["priority"] == p)
           for p in PRIORITY_ORDER}

if summary["critica"] >= 1:
    global_status = "blocked"
elif summary["alta"] >= 3:
    global_status = "partial"
else:
    global_status = "ready"

features_result.sort(key=lambda f: (PRIORITY_ORDER.index(f["priority"]), f.get("completion_pct", 50)))

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

**Required sections to cover** (read the corresponding section in `data/all-features.md` for each):

| Section | Title | Key AD source |
|---------|-------|---------------|
| 1.1 | Maintain Windows | AD_WINDOW.xml WINDOWTYPE=M |
| 1.2 | Transaction Windows / State Machine | AD_WINDOW.xml WINDOWTYPE=T + COLUMNNAME=DocAction |
| 1.3 | Query / Info Windows | AD_WINDOW.xml WINDOWTYPE=Q |
| 1.4 | Pick and Execute | AD_WINDOW.xml WINDOWTYPE=OBUIAPP_PickAndExecute |
| 2 | Reference Types (advanced fields) | AD_COLUMN.xml AD_REFERENCE_ID (Image, Color, BLOB, etc.) |
| 3 | Process Definitions (modern) | OBUIAPP_PROCESS.xml |
| 3b | Legacy Processes & Reports | AD_PROCESS.xml ISREPORT=Y / UIPATTERN |
| 4 | Display Logic (field visibility) | AD_FIELD.xml DISPLAYLOGIC |
| 5 | Tab behaviors (SR, read-only, display logic) | AD_TAB.xml UITYPE/ISREADONLY/DISPLAYLOGIC |
| 6 | Callouts | AD_COLUMN.xml CALLOUT (esp. OB.* namespace) |
| 8 | Selectors with out-parameters | OBUISEL_SELECTORFIELD.xml ISOUTPARAMETER=Y |
| 10 | Cross-cutting: Attachments, Notes, Copy | AD_TAB.xml ISALLOWATTACHMENT/ISALLOWNOTES |
| 10b | Read-only logic | AD_COLUMN.xml READONLYLOGIC |
| 18 | Application Forms (AD_FORM) | AD_FORM.xml |
| 19 | Linked Items / KMO | OBKMO_*.xml |
| 21 | Workspace / Dashboard Widgets | OBKMO_WIDGET*.xml |
| 22 | Field Groups | AD_FIELD.xml AD_FIELDGROUP_ID |
| 23 | Status Bar Fields | AD_FIELD.xml ISSHOWNINSTATUSBAR=Y |
| 29 | Tree Views | AD_TAB.xml HASTREE=Y |

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

  Custom modules        : N items
    → X bundle candidates
    → Y client-specific

  Unmaintained modules  : N items
    → X high risk
    → Y medium risk
    → Z low risk

  ─────────────────────────────────────────────
  RUTA A: Actualización a 25.4.x
    Core          :  Nh
    Custom        :  Nh
    Sin mant.     :  Nh
    TOTAL         :  Nh

  RUTA B: Migración a SaaS
    Core          :  Nh
    Custom        :  Nh
    Sin mant.     :  Nh
    TOTAL         :  Nh
  ─────────────────────────────────────────────

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
- **UI Readiness is quantified** — every `reason` field must include the actual count found in this client's AD (e.g., "47 ventanas Transaction", "312 campos con display logic", "18 callouts OB.*"). Never write a generic reason. Read the corresponding section in `data/all-features.md` to understand what the feature does before writing the reason.
- **Never use `ui_feature_map.json`** — the source of truth for UI feature descriptions is `data/all-features.md`. The feature map JSON is deprecated.
