---
description: "Enriches an Etendo client's custom_assessment with Mixpanel real usage data: usage_score, windows_used, elimination_candidate per module"
argument-hint: "[client-name] [mixpanel-instance?]"
---

# etendo-mixpanel-usage

**Arguments:** `$ARGUMENTS` — client name (e.g. `enertis`) and optionally the Mixpanel instance name. If the instance name is omitted, use the client name as the instance.

You are an Etendo migration analyst. Your job is to cross-reference the client's `custom_assessment` modules with **real usage data from Mixpanel** to determine which modules are actively used, which are dead weight, and which can be safely eliminated before migration.

---

## Step 1 — Locate the report

Resolve `$ARGUMENTS` into a client slug and an optional Mixpanel instance name:
- Client slug: lowercase, spaces → underscores (e.g. `"Etendo 26 Local"` → `etendo_26_local`)
- Mixpanel instance: if not given in `$ARGUMENTS`, use the client slug

Load the report:
```bash
cat reports/{client}.json
```

Extract:
- `custom_assessment.custom_modules` — custom modules list
- `custom_assessment.unmaintained_modules` — unmaintained modules list
- Installation root: infer from any `path` field in `modules.gradle_source`, `modules.custom`, or `modules.local_not_maintained`

---

## Step 1b — Resolve Mixpanel source_instance (manual overrides)

Some clients use a `source_instance` value in Mixpanel that doesn't match their slug. **Before querying Mixpanel**, check if the client slug has a known manual override and use that value instead:

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
}

# If no instance was given in $ARGUMENTS, use override or slug as fallback
if mixpanel_instance is None:
    mixpanel_instance = MANUAL_MIXPANEL_OVERRIDES.get(client_slug, client_slug)
```

> If the user reports a new mapping (e.g. "client X appears in Mixpanel as Y"), add it here.

---

## Step 2 — Authenticate with Mixpanel

Use the `mcp__claude_ai_Mixpanel__authenticate` tool to connect to the client's Mixpanel instance. The instance name to use is the one resolved in Step 1b.

---

## Step 3 — Extract window and process names per module

For each module in `custom_modules` and `unmaintained_modules` that has a `path` field (or whose path can be inferred from `{install_root}/modules/{java_package}`):

Extract the windows and processes defined in the module by reading:
- `{module_path}/src-db/database/sourcedata/AD_WINDOW.xml` → `<NAME>` tags → window names
- `{module_path}/src-db/database/sourcedata/AD_MENU.xml` → entries with `<ACTION>P</ACTION>` → process names referenced

```python
import xml.etree.ElementTree as ET
from pathlib import Path

def extract_window_names(module_path):
    """Extract window names defined in this module."""
    names = []
    for xml_file in ["AD_WINDOW.xml", "AD_FORM.xml"]:
        p = Path(module_path) / "src-db/database/sourcedata" / xml_file
        if p.exists():
            try:
                tree = ET.parse(p)
                for elem in tree.findall(".//*[NAME]"):
                    n = elem.find("NAME")
                    if n is not None and n.text:
                        names.append(n.text.strip())
            except Exception:
                pass
    return list(set(names))

def extract_process_names(module_path):
    """Extract process/form names from AD_PROCESS.xml and AD_FORM.xml."""
    names = []
    for xml_file in ["AD_PROCESS.xml"]:
        p = Path(module_path) / "src-db/database/sourcedata" / xml_file
        if p.exists():
            try:
                tree = ET.parse(p)
                for elem in tree.findall(".//*[NAME]"):
                    n = elem.find("NAME")
                    if n is not None and n.text:
                        names.append(n.text.strip())
            except Exception:
                pass
    return list(set(names))
```

If a module has no `path` but you know its `java_package`, construct the path as `{install_root}/modules/{java_package}`.

Modules with no XML source files (e.g. translation modules, template-only modules with no sourcedata) → skip extraction, mark as `windows_used: [], windows_unused: [], usage_score: 0`.

---

## Step 4 — Query Mixpanel for each module's windows

For each window/process name extracted in Step 3, query Mixpanel to count events in the last **90 days**.

Use the Mixpanel MCP tools to:
1. Look up the event property that identifies the window or process being accessed (typically a property like `windowId`, `window`, `processId`, or `tabId` on navigation/view events).
2. Query the count of events where that property matches the window name or ID.

**Important:** Mixpanel event property names vary by Etendo version. Common patterns:
- Event name: `"Window Opened"`, `"Tab Loaded"`, `"Process Executed"`, or similar
- Property: `"windowName"`, `"window_name"`, `"title"`, `"processName"`

If in doubt, first fetch a sample of recent events to inspect the property schema before querying.

Group results by window name. For each window:
- **Used**: ≥ 1 event in 90 days → add to `windows_used`
- **Not used**: 0 events → add to `windows_unused`

---

## Step 5 — Compute usage_score and elimination_candidate per module

**Usage score** (0–5 scale based on total events across all module windows in 90 days):

| Total events | Score |
|---|---|
| 0 | 0 |
| 1 – 100 | 1 |
| 101 – 500 | 2 |
| 501 – 2.000 | 3 |
| 2.001 – 10.000 | 4 |
| > 10.000 | 5 |

**elimination_candidate:**
- `true` if `usage_score == 0` AND (`generalization != "bundle_candidate"`)
- `false` otherwise — even if score is low, do not mark as elimination candidate if the module is a bundle candidate

**For translation modules** (java_package ends in `_es_ES`, `_es_es`, `_en_US`, etc.):
- Set `usage_score: 0`, `windows_used: []`, `windows_unused: []`, `elimination_candidate: false`
- Their fate follows the main module.

---

## Step 6 — Update custom_assessment in the JSON

Add the following fields to each module entry in `custom_modules` and `unmaintained_modules`:
```json
{
  "usage_score": 3,
  "windows_used": ["Sales Invoice", "Purchase Invoice"],
  "windows_unused": ["Goods Receipt"],
  "elimination_candidate": false
}
```

Also update the top-level `custom_assessment` object:
```json
{
  "mixpanel_source_instance": "{instance_name}",
  "mixpanel_date_range": "90 días"
}
```

Update `effort_summary` with elimination stats:
```python
elim_candidates = [
    m for m in custom_modules + unmaintained_modules
    if m.get("elimination_candidate", False)
]
effort_saved_min = sum(m.get("effort_days_min", 0) for m in elim_candidates)
effort_saved_max = sum(m.get("effort_days_max", 0) for m in elim_candidates)

effort_summary["elimination_candidates"] = len(elim_candidates)
effort_summary["effort_saved_eliminating_min"] = effort_saved_min
effort_summary["effort_saved_eliminating_max"] = effort_saved_max
```

Write the updated report:
```python
import json
from pathlib import Path

report_path = Path("reports/{client}.json")
with open(report_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print(f"✓ Mixpanel usage data written to {report_path}")
```

---

## Step 7 — Regenerate HTML

```bash
python3 report_html.py --input reports/{client}.json --output reports/{client}.html
```

---

## Output format

End with a summary using this format:

```
✓ Mixpanel usage analysis — {client_name}
  Instance: {mixpanel_instance} · Last 90 days

  Custom modules        : N analyzed
    → X with active usage (score ≥ 1)
    → Y with zero usage (elimination candidates)

  Unmaintained modules  : N analyzed
    → X with active usage
    → Y elimination candidates

  ─────────────────────────────
  Elimination candidates: N modules
  Effort saved if eliminated: X–Y days

  report.json updated: reports/{client}.json
  HTML regenerated   : reports/{client}.html
```

---

## Important rules

- **Never mark a module as elimination_candidate based on name alone** — always confirm with Mixpanel data.
- **If Mixpanel returns no data for a window**, it could mean the window is unused OR that the event property name doesn't match. Note the uncertainty in the reason field.
- **Modules with `generalization: "bundle_candidate"`** are never elimination candidates even at score 0 — they may be valuable for other clients.
- **Translation modules** follow the fate of their parent module — don't analyze them separately.
- **Update recommendations** for modules where Mixpanel data changes the picture: if a module was previously "medium risk" but has zero usage, strengthen the recommendation to eliminate; if it has high usage, emphasize migration priority.
