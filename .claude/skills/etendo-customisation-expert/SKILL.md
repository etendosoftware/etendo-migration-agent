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

**Two required reference files — read both before writing any feature entry:**
- `data/all-features.md` — describes each feature's expected behavior, checklist, and real examples. Use it to understand context and draft specific `reason` fields.
- `data/all-features-analysis.md` — contains the **authoritative `status` and `% Real` (completion_pct) for each section** based on actual analysis of the React codebase. Always use the values from this file for `status` and `completion_pct`. Do NOT rely on your training data for these values.

Do NOT use `ui_feature_map.json`.

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
# ─────────────────────────────────────────────────
# SECTION 1 — Window Types (Sections 1.1–1.4)
# ─────────────────────────────────────────────────

# 1. All window types breakdown: M / T / Q / OBUIAPP_PickAndExecute
grep -rh "WINDOWTYPE=" {sourcedata_dirs} --include="AD_WINDOW.xml" \
  | grep -oE 'WINDOWTYPE="[^"]+"' | sort | uniq -c
# Critical for priority: T (Transaction) and OBUIAPP_PickAndExecute are the riskiest

# ─────────────────────────────────────────────────
# SECTION 2 — Reference Types (field widgets)
# ─────────────────────────────────────────────────

# 2. Full AD_REFERENCE_ID distribution — cross-reference with all-features-analysis.md Section 2
grep -rh 'AD_REFERENCE_ID=' {sourcedata_dirs} --include="AD_COLUMN.xml" \
  | grep -oE 'AD_REFERENCE_ID="[^"]+"' | sort | uniq -c | sort -rn
# Cross-reference the distribution above with Section 2 of all-features-analysis.md. 
# Only include reference types that are actually present in this client's AD (count > 0) 
# AND are classified as NOT DONE or PARCIAL in analysis.md.
# Key IDs to flag if > 0 (NOT DONE / PARCIAL in analysis.md):
#   Rich Text     7CB371C1...   WYSIWYG editor          NOT DONE
#   Image BLOB    4AA6C3BE...   binary image upload     PARCIAL
#   Upload File   715C53D4...   file upload drag-drop   NOT DONE
#   Color         27            color picker            NOT DONE
#   Assignment    33            resource assign popup   NOT DONE
#   PAttribute    35            product attr set        PARCIAL
#   Multi Selector 87E6CFF8...  tag multi-select        NOT DONE
#   SelectorAsLink 80B16307...  clickable FK link       PARCIAL
#   Tree Reference 8C57A4A2...  hierarchical selector   NOT DONE
#   Binary        23            file BLOB               PARCIAL
#   Image         32            ad_image reference      PARCIAL

# ─────────────────────────────────────────────────
# SECTION 2.B — Hardcoded Button Columns (HTML Templates)
# ─────────────────────────────────────────────────

# 3. Special-case hardcoded button column names (each requires dedicated reimplementation)
grep -rh "COLUMNNAME=" {sourcedata_dirs} --include="AD_COLUMN.xml" \
  | grep -E 'COLUMNNAME="(DocAction|Posted|CreateFrom|PaymentRule|ChangeProjectStatus)"' \
  | grep -oE 'COLUMNNAME="[^"]+"' | sort | uniq -c

# 4. Modern vs legacy button routing: columns with em_obuiapp_process_id (modern) vs ad_process_id (legacy)
grep -rc 'EM_OBUIAPP_PROCESS_ID=' {sourcedata_dirs} --include="AD_COLUMN.xml"
grep -rc 'AD_PROCESS_ID='         {sourcedata_dirs} --include="AD_COLUMN.xml"

# ─────────────────────────────────────────────────
# SECTION 3 — Process Types (both AD entities)
# ─────────────────────────────────────────────────

# 5. AD_PROCESS (Report and Process) — UIPattern breakdown: S / M / OBUIAPP_PickAndExecute
grep -rh "UIPATTERN=" {sourcedata_dirs} --include="AD_PROCESS.xml" \
  | grep -oE 'UIPATTERN="[^"]+"' | sort | uniq -c

# 6. AD_PROCESS special flags (Section 3.A.2 sub-categories)
grep -rc 'ISREPORT="Y"'     {sourcedata_dirs} --include="AD_PROCESS.xml"  # legacy HTML/PDF reports
grep -rc 'ISBACKGROUND="Y"' {sourcedata_dirs} --include="AD_PROCESS.xml"  # scheduled background
grep -rc 'ISJASPER="Y"'     {sourcedata_dirs} --include="AD_PROCESS.xml"  # Jasper engine (Section 3.A.4)
grep -rh "UIPATTERN=" {sourcedata_dirs} --include="AD_PROCESS.xml" \
  | grep -c 'UIPATTERN="M"'  # Manual JS processes — BLOQUEADO (OB.* namespaces missing in React)

# 7. OBUIAPP_PROCESS (Process Definition) — UIPattern breakdown: A / M / OBUIAPP_PickAndExecute / OBUIAPP_Report / ETRX_RxAction
grep -rh "UIPATTERN=" {sourcedata_dirs} --include="OBUIAPP_PROCESS.xml" \
  | grep -oE 'UIPATTERN="[^"]+"' | sort | uniq -c

# 8. OBUIAPP_PROCESS parameters — processes with AD-defined parameter popups (Section 3.B.3)
grep -rc "<OBUIAPP_PARAMETER " {sourcedata_dirs} --include="OBUIAPP_PARAMETER.xml"

# ─────────────────────────────────────────────────
# SECTION 4 — Display Logic (field visibility)
# ─────────────────────────────────────────────────

# 9. Display Logic on fields (Section 4) — total count
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_FIELD.xml"
# Sub-count: fields using @$SessionVar@ (session-aware visibility — harder to compute)
grep -rh "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_FIELD.xml" | grep -c '@\$'

# 10. Display Logic on columns (column-level visibility)
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_COLUMN.xml"

# ─────────────────────────────────────────────────
# SECTION 5 — Tab-Level Behaviors
# ─────────────────────────────────────────────────

# 11. Tab-level Display Logic — tab visibility (Section 5.1)
grep -rc "DISPLAYLOGIC=" {sourcedata_dirs} --include="AD_TAB.xml"

# 12. Read-only tabs ISREADONLY=Y (Section 5.2)
grep -rc 'ISREADONLY="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 13. Tab UI type breakdown: STD / RO / ED / SR (Section 5.3)
grep -rh "UITYPE=" {sourcedata_dirs} --include="AD_TAB.xml" \
  | grep -oE 'UITYPE="[^"]+"' | sort | uniq -c
# SR = Single Record form-only; ED = Editable inline grid

# 14. Grid-initial tabs ISSHOWNINITIALGRIDMODE=Y (Section 9 — grid default)
grep -rc 'ISSHOWNINITIALGRIDMODE="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 15. Tab default filters and sort orders (Section 26)
grep -rc "HQLFILTERCLAUSE=" {sourcedata_dirs} --include="AD_TAB.xml"
grep -rc "FILTERCLAUSE="    {sourcedata_dirs} --include="AD_TAB.xml"

# ─────────────────────────────────────────────────
# SECTION 6 — Callouts
# ─────────────────────────────────────────────────

# 16. Callout-linked columns (Section 6)
grep -rc "<CALLOUT>" {sourcedata_dirs} --include="AD_COLUMN.xml"
# Sub-count: top unique callout classes (complexity gauge)
grep -rh "<CALLOUT>" {sourcedata_dirs} --include="AD_COLUMN.xml" \
  | grep -oE '<CALLOUT>[^<]+</CALLOUT>' | sort | uniq -c | sort -rn | head -20

# ─────────────────────────────────────────────────
# SECTION 7 — Record State Machine
# NOTE: Covered by count #1 (Transaction windows) and #3 (hardcoded buttons).
# No additional grep required.
# ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────
# SECTION 8 — Selectors and FK Fields
# ─────────────────────────────────────────────────

# 17. OBUISEL Selector definitions total (Section 8)
grep -rc "<OBUISEL_SELECTOR " {sourcedata_dirs} --include="OBUISEL_SELECTOR.xml"

# 18. Selector out-parameters — selectors populating multiple fields on selection (Section 8)
grep -rc 'ISOUTPARAMETER="Y"' {sourcedata_dirs} --include="OBUISEL_SELECTORFIELD.xml"
grep -rl 'ISOUTPARAMETER="Y"' {sourcedata_dirs} --include="OBUISEL_SELECTORFIELD.xml" | wc -l  # distinct selectors

# 19. Multi-selector columns (reference type 87E6CFF8* — tag/chip multi-select)
grep -rh "AD_REFERENCE_ID=" {sourcedata_dirs} --include="AD_COLUMN.xml" | grep -c '87E6CFF8'

# 20. SelectorAsLink columns (reference type 80B16307* — clickable FK link)
grep -rh "AD_REFERENCE_ID=" {sourcedata_dirs} --include="AD_COLUMN.xml" | grep -c '80B16307'

# ─────────────────────────────────────────────────
# SECTION 9 — Grid Behaviors
# ─────────────────────────────────────────────────

# 21. Editable grid tabs (UITYPE=ED — inline cell editing, Section 9.4)
grep -rh "UITYPE=" {sourcedata_dirs} --include="AD_TAB.xml" | grep -c 'UITYPE="ED"'

# 22. Selection columns — fields in grid filter row by default (Section 24.3)
grep -rc 'ISSELECTIONCOLUMN="Y"' {sourcedata_dirs} --include="AD_COLUMN.xml"

# ─────────────────────────────────────────────────
# SECTION 10 — Cross-Cutting Behaviors
# ─────────────────────────────────────────────────

# 23. Attachment-enabled tabs (Section 10.4)
grep -rc 'ISALLOWATTACHMENT="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 24. Notes-enabled tabs (Section 10.5)
grep -rc 'ISALLOWNOTES="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 25. Copy Record with child tab deep copy (Section 10.6)
grep -rc 'ENABLECOPYFULL="Y"'          {sourcedata_dirs} --include="AD_TAB.xml"
grep -rc 'ENABLECOPYRELATIONSHIPS="Y"' {sourcedata_dirs} --include="AD_TAB.xml"

# 26. Read-only logic — conditional editability (Section 10 / 14)
grep -rc "READONLYLOGIC=" {sourcedata_dirs} --include="AD_COLUMN.xml"
grep -rh "READONLYLOGIC=" {sourcedata_dirs} --include="AD_COLUMN.xml" | grep -c '@\$'  # session-var deps

# 27. Always-read-only columns isupdateable=N (Section 24.4)
grep -rc 'ISUPDATEABLE="N"' {sourcedata_dirs} --include="AD_COLUMN.xml"

# ─────────────────────────────────────────────────
# SECTIONS 13 / 25 — Form Init & Default Values
# ─────────────────────────────────────────────────

# 28. All columns with any default value defined (Section 25)
grep -rc "DEFAULTVALUE=" {sourcedata_dirs} --include="AD_COLUMN.xml"

# 29. Complex defaults requiring server-side resolution: session vars or SQL (Section 25.2)
grep -rh "DEFAULTVALUE=" {sourcedata_dirs} --include="AD_COLUMN.xml" \
  | grep -cE 'DEFAULTVALUE="(@|SELECT )'

# 30. Mandatory fields — scope of client-side form validation (Section 13.1)
grep -rc 'ISMANDATORY="Y"' {sourcedata_dirs} --include="AD_COLUMN.xml"

# ─────────────────────────────────────────────────
# SECTION 18 — Application Forms (ad_form)  [NOT DONE ~5%]
# ─────────────────────────────────────────────────

# 31. Application Forms count (each = custom servlet UI with no standard window/tab/field pattern)
grep -rc "<AD_FORM " {sourcedata_dirs} --include="AD_FORM.xml"
grep -rl "<AD_FORM " {sourcedata_dirs} --include="AD_FORM.xml" | wc -l  # modules providing forms

# ─────────────────────────────────────────────────
# SECTIONS 19 / 21 — Linked Items & Dashboard Widgets  [NOT DONE]
# ─────────────────────────────────────────────────

# 32. KMO / Linked Items infrastructure presence
grep -rl "OBKMO\|LinkedItem\|WidgetClass" {sourcedata_dirs} --include="*.xml" | wc -l

# 33. Widget class and instance counts (Section 21.2 — My Openbravo / Workspace)
grep -rc "<OBKMO_WIDGET_CLASS "    {sourcedata_dirs} --include="OBKMO_WIDGET_CLASS.xml"
grep -rc "<OBKMO_WIDGET_INSTANCE " {sourcedata_dirs} --include="OBKMO_WIDGET_INSTANCE.xml"
grep -rc "<OBKMO_WIDGET_URL "      {sourcedata_dirs} --include="OBKMO_WIDGET_URL.xml"
grep -rc "<OBCQL_WIDGET_QUERY "    {sourcedata_dirs} --include="OBCQL_WIDGET_QUERY.xml"

# ─────────────────────────────────────────────────
# SECTION 22 — Field Groups (collapsible form sections)
# ─────────────────────────────────────────────────

# 34. Field Groups — total fields assigned to collapsible sections (Section 22)
grep -rc "AD_FIELDGROUP_ID=" {sourcedata_dirs} --include="AD_FIELD.xml"
# Sub-count: number of distinct field groups used
grep -rh "AD_FIELDGROUP_ID=" {sourcedata_dirs} --include="AD_FIELD.xml" \
  | grep -oE 'AD_FIELDGROUP_ID="[^"]+"' | sort -u | wc -l

# ─────────────────────────────────────────────────
# SECTION 23 — Status Bar Fields
# ─────────────────────────────────────────────────

# 35. Fields displayed in the status bar (Section 23)
grep -rc 'ISSHOWNINSTATUSBAR="Y"' {sourcedata_dirs} --include="AD_FIELD.xml"

# ─────────────────────────────────────────────────
# SECTION 29 — Tree Views
# ─────────────────────────────────────────────────

# 36. Tree-enabled tabs (Section 29)
grep -rc 'HASTREE="Y"'   {sourcedata_dirs} --include="AD_TAB.xml"
grep -rc "TREECATEGORY=" {sourcedata_dirs} --include="AD_TAB.xml"

# ─────────────────────────────────────────────────
# SECTION 32 — Alert System
# ─────────────────────────────────────────────────

# 37. Alert rules defined (Section 32 — depends on background Alert Process)
grep -rc "<AD_ALERTRULE " {sourcedata_dirs} --include="AD_ALERTRULE.xml"

# ─────────────────────────────────────────────────
# SECTION 33 — View Personalization (Saved Views)
# ─────────────────────────────────────────────────

# 38. Saved UI personalizations in AD (Section 33 — OBUIAPP_UIPersonalization table)
grep -rc "<OBUIAPP_UIPERSONALIZATION " {sourcedata_dirs} --include="OBUIAPP_UIPERSONALIZATION.xml"

# ─────────────────────────────────────────────────
# SECTION 34 — Calendar Views
# ─────────────────────────────────────────────────

# 39. Calendar widget usage in AD (Section 34 — OBCalendar / OBMultiCalendar references)
grep -rl "ob-calendar\|OBCalendar\|OBMultiCalendar" {sourcedata_dirs} --include="*.xml" | wc -l

# ─────────────────────────────────────────────────
# SECTIONS 12 / 20 — Navigation, Menu & Quick Launch
# ─────────────────────────────────────────────────

# 40. Total menu entries and type breakdown (Section 12, 20)
grep -rc "<AD_MENU " {sourcedata_dirs} --include="AD_MENU.xml"
grep -rh 'ACTION=' {sourcedata_dirs} --include="AD_MENU.xml" \
  | grep -oE 'ACTION="[^"]+"' | sort | uniq -c
# W=Window, P=Process (R&P legacy), R=Report, X=Form/External,
# OBUIAPP_Process=Process Definition, blank=Summary/Folder
```

> **Coverage note — sections with no AD-greeppable data:**
> The following sections have NO structural data in the AD XML files.
> They describe runtime behaviors, UI shell features, or code-only configuration.
> They must be assessed by code review or manual QA, not by counting:
>
> | Section | Reason |
> |---------|--------|
> | §11 — Authentication & Session | JWT/login is Java config, not AD XML data |
> | §15 — Loading Indicators & Feedback | Pure UI behavior, no AD representation |
> | §16 — Final Consistency Validation | QA acceptance checklist only |
> | §17 — Toolbar Buttons | Standard buttons are hardcoded in JS; module buttons in code |
> | §27 — Multi-Window Tab Interface (MDI) | Shell behavior, no AD data |
> | §28 — Keyboard Shortcuts | Stored as `OBUIAPP_KeyboardShortcuts` preference string, not per-window |
> | §30 — Grouping in Grid View | Controlled by 2 global preferences (`OBUIAPP_GroupingEnabled`, `OBUIAPP_GroupingMaxRecords`) |
> | §31 — Data Import System | `c_import_entry` table is core infrastructure, not customer-configurable |
>
> For these sections: set `priority = "no_aplica"` unless the client explicitly uses that feature.

---

**Additional counts for Section 24 — Form Layout System:**

```bash
# ─────────────────────────────────────────────────
# SECTION 24 — Form Layout System
# ─────────────────────────────────────────────────

# 41. Fields forcing a new row (STARTROW / STARTNEWLINE) — affect form column layout (Section 24.2)
grep -rc 'STARTROW="Y"'    {sourcedata_dirs} --include="AD_FIELD.xml"
grep -rc 'STARTNEWLINE="Y"' {sourcedata_dirs} --include="AD_FIELD.xml"

# 42. Multi-column span fields (NUMCOLUMN > 1) — full-width fields like Memo, Rich Text (Section 24.2)
grep -rh 'NUMCOLUMN=' {sourcedata_dirs} --include="AD_FIELD.xml" \
  | grep -oE 'NUMCOLUMN="[^"]+"' | sort | uniq -c

# 43. Key column-level flags affecting grid and form rendering (Section 24.3, 24.4)
grep -rc 'ISIDENTIFIER="Y"'    {sourcedata_dirs} --include="AD_COLUMN.xml"  # compose record display string
grep -rc 'ISPARENT="Y"'        {sourcedata_dirs} --include="AD_COLUMN.xml"  # FK to parent tab (usually hidden)
grep -rc 'ISENCRYPTED="Y"'     {sourcedata_dirs} --include="AD_COLUMN.xml"  # masked encrypted value
grep -rc 'ISSECONDARYKEY="Y"'  {sourcedata_dirs} --include="AD_COLUMN.xml"  # secondary unique key (lookup)
grep -rc 'ISFIRSTFOCUSEDFIELD="Y"' {sourcedata_dirs} --include="AD_FIELD.xml"  # auto-focus on form open
grep -rc 'SHOWINGRIDVIEW="N"'      {sourcedata_dirs} --include="AD_FIELD.xml"  # form-only fields (hidden in grid)
```

---

### Sub-step A3 — Assign priority per feature

| Count in this client's AD | Feature/Section Type | Priority |
|--------------------------|----------------------|----------|
| **Any count** | **Architectural Blockers** (see list below) | **critica** |
| > 50 instances OR > 20 windows | NOT DONE / PARCIAL / BUG ACTIVO | **critica** |
| 10–50 instances OR 5–20 windows | NOT DONE / PARCIAL / BUG ACTIVO | **alta** |
| < 10 instances | NOT DONE / PARCIAL / BUG ACTIVO | **media** |
| 0 instances found | any | **no_aplica** |
| any count | DONE / TO CHECK | **media** or **no_aplica** |

> **Architectural Blockers — Always prioritize as "critica" if found (>0 count):**
> - **§3.B.2 / §3.A.2 (Manual Action/JS Processes):** Hard blocker because the `OB.*` namespaces (Classic UI) are missing in React. Modules relying on this for Picking, Packing, or Period management cannot work without a complete rewrite or iframe shim.
> - **§2.B / §2.B.2 (Hardcoded Button Processes):** Essential columns like `DocAction`, `Posted`, `CreateFrom`, `PaymentRule`, and `ChangeProjectStatus` that rely on legacy HTML templates. Each requires a dedicated React component rather than the standard metadata-driven pattern.
> - **§18 (Application Forms - AD_FORM):** Critical business wizards and batch flows (Initial Client Setup, Invoice/Shipment generation) not yet ported to React.
> - **§21 (Workspace/Dashboard Widgets):** No React API contract yet for custom JS widgets.
> - **§4 (Display Logic @field@ syntax):** Active production bug that causes JavaScript crashes in any window using this common syntax.
> - **§8 (Selector Out Parameters):** Critical for data efficiency; without this, auto-filling multiple fields from a single selection is broken.

```python
PRIORITY_ORDER = ["critica", "alta", "media", "no_aplica"]

# Build features list from your analysis above
# One entry per logical feature section (not per XML file)
features_result = [
    # Example structure — fill in from your Sub-step A2/A3 analysis:
    {
        "section": "1.2",
        "title": "Transaction Windows (Document State Machine)",
        # status → from all-features-analysis.md Section 1.2 Estado label
        "status": "TO CHECK",
        # completion_pct → from all-features-analysis.md Section 1.2 % Real value
        "completion_pct": 78,
        "priority": "critica",   # or alta/media/no_aplica
        # reason must include: (a) actual count, (b) what that means for the client,
        # (c) the specific gap from all-features-analysis.md for this section
        "reason": "Este cliente tiene N ventanas Transaction (pedidos, facturas, pagos). Según all-features-analysis.md sección 1.2, el estado es TO CHECK al 78%. Las brechas clave son: DocAction labels incorrectos (bug activo), Posted button parcial (30%), y protección de edición concurrente no validada.",
        "ad_count": 47,           # actual count from grep
        "code_evidence": []       # leave empty — evidence is the count above
    },
    # ... one entry per section listed in the table below
]

summary = {p: sum(1 for f in features_result if f["priority"] == p)
           for p in PRIORITY_ORDER}

if summary["critica"] >= 1:
    global_status = "blocked"
elif summary["alta"] >= 3:
    global_status = "partial"
else:
    global_status = "ready"

# Platform-level floor: overall completion is ~62%.
# Never set global_status to "ready" if there are NOT DONE or BLOQUEADO features 
# that are NOT "no_aplica" for this client.
if global_status == "ready" and any(f["status"] in ("NOT DONE", "BLOQUEADO") 
                                    for f in features_result 
                                    if f["priority"] != "no_aplica"):
    global_status = "partial"

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

**Required sections to cover** (read the corresponding section in both `data/all-features.md` AND `data/all-features-analysis.md` for each — the first for context, the second for `status`/`completion_pct`). **If a section is missing in `all-features-analysis.md`, assume its completion_pct is 0%**:

| Section | Title | Key AD source (grep count #) | analysis.md ref | Greepable? |
|---------|-------|------------------------------|-----------------|------------|
| **1.1** | Maintain Windows | AD_WINDOW WINDOWTYPE=M (#1) | Section 1.1 | ✅ |
| **1.2** | Transaction Windows + State Machine | AD_WINDOW WINDOWTYPE=T (#1) + COLUMNNAME=DocAction (#3) | Section 1.2 | ✅ |
| **1.3** | Query / Info Windows | AD_WINDOW WINDOWTYPE=Q (#1) | Section 1.3 | ✅ |
| **1.4** | Pick and Execute Windows | AD_WINDOW WINDOWTYPE=OBUIAPP_PickAndExecute (#1) | Section 1.4 | ✅ |
| **2** | Reference Types (unimplemented field widgets) | AD_COLUMN AD_REFERENCE_ID distribution (#2) — flag types with >0 listed as NOT DONE in analysis.md | Section 2 | ✅ |
| **2.B** | Hardcoded Button Columns (DocAction, Posted, CreateFrom…) | AD_COLUMN COLUMNNAME in (5 special names) (#3) + legacy vs modern routing (#4) | Section 2.B | ✅ |
| **3** | Process Definitions — modern (OBUIAPP) | OBUIAPP_PROCESS UIPattern breakdown (#7) + parameters (#8) | Section 3.B | ✅ |
| **3b** | Legacy Processes & Reports (AD_PROCESS) | AD_PROCESS UIPattern (#5) + ISREPORT/ISBACKGROUND/ISJASPER/UIPATTERN=M (#6) | Section 3.A | ✅ |
| **4** | Display Logic (field visibility) | AD_FIELD DISPLAYLOGIC (#9) + AD_COLUMN DISPLAYLOGIC (#10) | Section 4 | ✅ |
| **5** | Tab behaviors (SR, ED, read-only, display logic, filters) | AD_TAB UITYPE breakdown (#13) + ISREADONLY (#12) + DISPLAYLOGIC (#11) + HQLFILTERCLAUSE (#15) | Section 5 | ✅ |
| **6** | Callouts | AD_COLUMN CALLOUT count + distinct classes (#16) | Section 6 | ✅ |
| **7** | Record State Machine | Covered by §1.2 (Transaction windows) + §2.B (DocAction button). No extra grep. | Section 7 | ✅ |
| **8** | Selectors (OBUISEL) + out-parameters | OBUISEL_SELECTOR count (#17) + ISOUTPARAMETER=Y (#18) + Multi/SelectorAsLink (#19,#20) | Section 8 | ✅ |
| **9** | Grid behaviors (editable grids, grid-initial tabs) | AD_TAB UITYPE=ED (#21) + ISSHOWNINITIALGRIDMODE=Y (#14) + ISSELECTIONCOLUMN (#22) | Section 9 | ✅ |
| **10** | Cross-cutting: Attachments, Notes, Copy Record, Read-only logic | AD_TAB ISALLOWATTACHMENT/ISALLOWNOTES (#23,#24) + ENABLECOPYFULL (#25) + AD_COLUMN READONLYLOGIC (#26) + ISUPDATEABLE=N (#27) | Section 10 | ✅ |
| **11** | Authentication, Session & Authorization | ⚠️ No AD XML data — JWT/login is Java config | Section 11 | ❌ `no_aplica` |
| **12** | Navigation & Menu System | AD_MENU count + ACTION breakdown (#40) | Section 12 | ✅ |
| **13** | Record Creation, Editing, Persistence | Covered by §4 (display logic), §6 (callouts), §25 (defaults), §10 (read-only logic) | Section 13 | ✅ (indirect) |
| **14** | Reports (standalone menu access) | Menu ACTION=R (#40) + ISREPORT=Y (#6) + OBUIAPP_Report (#7) + ISJASPER (#6) | Section 14 | ✅ |
| **15** | Loading Indicators & Feedback | ⚠️ Pure UI behavior — no AD XML representation | Section 15 | ❌ `no_aplica` |
| **16** | Final Consistency Validation | ⚠️ QA acceptance checklist only | Section 16 | ❌ `no_aplica` |
| **17** | Toolbar Buttons | ⚠️ Standard buttons hardcoded in JS; ENABLECOPYFULL (#25) for Clone | Section 17 | ❌ `no_aplica` (Clone via #25) |
| **18** | Application Forms (AD_FORM) | AD_FORM count (#31) | Section 18 | ✅ |
| **19** | Linked Items / KMO | OBKMO_*.xml file presence (#32) | Section 19 | ✅ |
| **20** | Quick Launch (Global Search) | Covered by §12 menu count — no separate AD artifact | Section 20 | ✅ (indirect) |
| **21** | Workspace / Dashboard Widgets | OBKMO_WIDGET_CLASS/INSTANCE/URL + OBCQL_WIDGET_QUERY (#33) | Section 21 | ✅ |
| **22** | Field Groups (collapsible form sections) | AD_FIELD AD_FIELDGROUP_ID count + distinct groups (#34) | Section 22 | ✅ |
| **23** | Status Bar Fields | AD_FIELD ISSHOWNINSTATUSBAR=Y (#35) | Section 23 | ✅ |
| **24** | Form Layout System | AD_FIELD STARTROW/STARTNEWLINE/NUMCOLUMN/ISFIRSTFOCUSEDFIELD/SHOWINGRIDVIEW (#41,#42) + AD_COLUMN ISIDENTIFIER/ISPARENT/ISENCRYPTED/ISSECONDARYKEY (#43) | Section 24 | ✅ |
| **25** | Default Value Expressions | AD_COLUMN DEFAULTVALUE total (#28) + complex SQL/@var (#29) + ISMANDATORY (#30) | Section 25 | ✅ |
| **26** | Tab Default Filters & Sort Order | AD_TAB HQLFILTERCLAUSE + FILTERCLAUSE (#15) | Section 26 | ✅ |
| **27** | Multi-Window Tab Interface (MDI) | ⚠️ Shell behavior — no AD XML artifact | Section 27 | ❌ `no_aplica` |
| **28** | Keyboard Shortcuts Reference | ⚠️ Global preference string, not per-window AD data | Section 28 | ❌ `no_aplica` |
| **29** | Tree Views | AD_TAB HASTREE=Y + TREECATEGORY (#36) | Section 29 | ✅ |
| **30** | Grouping in Grid View | ⚠️ 2 global preferences (OBUIAPP_GroupingEnabled, OBUIAPP_GroupingMaxRecords) | Section 30 | ❌ `no_aplica` |
| **31** | Data Import System | ⚠️ Core infrastructure table (c_import_entry), not customer-configurable | Section 31 | ❌ `no_aplica` |
| **32** | Alert System | AD_ALERTRULE count (#37) | Section 32 | ✅ |
| **33** | View Personalization (Saved Views) | OBUIAPP_UIPERSONALIZATION count (#38) | Section 33 | ✅ |
| **34** | Calendar Views | OBCalendar/OBMultiCalendar presence in XML (#39) | Section 34 | ✅ |
| **35** | View States (Form/Grid Layout) | Covered by §9 (grid-initial tabs) and §5 (tab patterns) | Section 35 | ✅ (indirect) |

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
