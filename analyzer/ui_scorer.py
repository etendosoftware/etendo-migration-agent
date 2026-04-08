"""
ui_scorer.py — Scores a client's ui_readiness section.

Per-feature usage_score (0.0–10.0):
  usage_ratio  = min(ad_count / ref_max, 1.0)
  usage_score  = usage_ratio × 10     (0 = not used, 10 = at reference max)

Overall ui_migration_score (0–100):
  For each scored feature:
    risk_i = usage_ratio_i × (1 − completion_pct_i / 100)
  ui_migration_score = (1 − Σ(risk_i × weight_i)) × 100

Labels:
  80–100  ready
  60–79   partial
  40–59   needs_work
  0–39    not_ready
"""

# ── Feature parameters ────────────────────────────────────────────────────────
# ref_max: typical upper bound for a large Etendo installation (usage beyond
#          this is capped at 10/10 — it doesn't get "worse" than the max)
# weight:  relative importance in the overall score; all weights must sum to 1.0

FEATURE_PARAMS: dict[str, dict] = {
    # High-impact engine-level features (new UI missing = broken forms)
    "4":       {"ref_max": 5000,  "weight": 0.15},  # Display Logic on fields
    "6":       {"ref_max": 200,   "weight": 0.12},  # Callouts (server-side on field change)
    "14":      {"ref_max": 2000,  "weight": 0.10},  # ReadOnly Logic (same as 4b, legacy name)
    "4b":      {"ref_max": 2000,  "weight": 0.10},  # ReadOnly Logic (new name)
    "2.B":     {"ref_max": 100,   "weight": 0.10},  # Hardcoded buttons (DocAction, Posted…)
    "5.1":     {"ref_max": 150,   "weight": 0.08},  # Tab Display Logic (tab visibility)
    "23":      {"ref_max": 500,   "weight": 0.08},  # Status Bar fields
    "AD_FORM": {"ref_max": 50,    "weight": 0.07},  # Application Forms (JS forms)
    "1.2":     {"ref_max": 100,   "weight": 0.06},  # Transaction windows (DocAction flow)
    # Medium-impact features
    "3":       {"ref_max": 1000,  "weight": 0.05},  # Process Definitions (legacy + OBUIAPP)
    "8":       {"ref_max": 500,   "weight": 0.05},  # OBUISEL Selectors
    "5.2":     {"ref_max": 60,    "weight": 0.04},  # Read-only tabs
    "1.4":     {"ref_max": 300,   "weight": 0.04},  # Pick and Execute windows
    "21":      {"ref_max": 50,    "weight": 0.03},  # KMO / Dashboard widgets
    # Lower-impact or mostly-done features
    "22":      {"ref_max": 3000,  "weight": 0.02},  # Field Groups (collapsible sections)
    "1.1":     {"ref_max": 500,   "weight": 0.01},  # Maintain windows (largely DONE)
    # These sections exist in reports but are not scored (weight=0 or ignored):
    # "7":  overlaps with "2.B", skip to avoid double-counting
    # "25": default values — too generic, not scored separately
    # "33": view personalization — minor UX impact
    # "1.3", "9", "12", "29", "11": DONE or negligible
}

# Only sections with weight > 0 and not duplicates participate in the score
_SCORED = {k: v for k, v in FEATURE_PARAMS.items() if v["weight"] > 0 and k != "4b"}
# If a report uses "14" (old name), treat same as "4b"; both share weight=0.10
# but only ONE should contribute. We handle this in compute_ui_score by
# picking whichever is present (14 takes precedence over 4b if both exist).


def compute_feature_score(feature: dict):
    """
    Returns usage_score (0.0–10.0) for a single feature dict, or None if
    the feature section is not in FEATURE_PARAMS.
    """
    section = feature.get("section", "")
    params = FEATURE_PARAMS.get(section)
    if params is None:
        return None
    ad_count = feature.get("ad_count") or 0
    usage_ratio = min(ad_count / params["ref_max"], 1.0)
    return round(usage_ratio * 10, 1)


def compute_ui_score(ui_readiness: dict):
    """
    Returns (ui_migration_score: int 0-100, label: str).
    """
    features = ui_readiness.get("features", [])
    if not features:
        return 100, "ready"

    # Index features by section for quick lookup
    by_section: dict[str, dict] = {}
    for f in features:
        by_section[f.get("section", "")] = f

    # "14" and "4b" are the same concept — pick whichever is present,
    # give full weight 0.10 to that one and skip the other.
    readonlylogic_key = "14" if "14" in by_section else "4b"

    weighted_risk = 0.0

    for section, params in FEATURE_PARAMS.items():
        weight = params["weight"]
        if weight == 0:
            continue
        # Skip the secondary readonlylogic key
        if section == "4b" and readonlylogic_key == "14":
            continue
        if section == "14" and readonlylogic_key == "4b":
            continue

        feat = by_section.get(section)
        if feat is None:
            continue  # feature not assessed for this client

        ad_count = feat.get("ad_count") or 0
        completion_pct = feat.get("completion_pct") or 0
        usage_ratio = min(ad_count / params["ref_max"], 1.0)
        incompleteness = (100 - completion_pct) / 100
        weighted_risk += usage_ratio * incompleteness * weight

    # weighted_risk is in [0, sum_of_weights] ≈ [0, 1]
    score = max(0, min(100, round((1 - weighted_risk) * 100)))

    if score >= 80:
        label = "ready"
    elif score >= 60:
        label = "partial"
    elif score >= 40:
        label = "needs_work"
    else:
        label = "not_ready"

    return score, label


def enrich_ui_readiness(ui_readiness: dict) -> dict:
    """
    Adds 'usage_score' to each feature and 'ui_migration_score' / 'ui_label'
    to the top-level ui_readiness dict. Returns the mutated dict.
    """
    for f in ui_readiness.get("features", []):
        score = compute_feature_score(f)
        f["usage_score"] = score  # None if section not in FEATURE_PARAMS

    ui_score, ui_label = compute_ui_score(ui_readiness)
    ui_readiness["ui_migration_score"] = ui_score
    ui_readiness["ui_label"] = ui_label
    return ui_readiness
