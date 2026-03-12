"""
migration_scorer.py — Calculates a migration score and migratability label.

Score: 0–100 (higher = easier to migrate to SaaS)

Penalties applied:
  - Platform is Openbravo (not Etendo)         → -20
  - Core divergences:
      per divergent file                        → -0.5 (capped at -25)
      per 100 diff lines (added+removed)        → -0.5 (capped at -15)
  - Modules not maintained by Etendo            → -3 per module (capped at -20)
  - Custom modules                              → -5 per module (capped at -25)
  - Etendo-maintained modules with divergences:
      per divergent file in module              → -0.2 (capped at -10 per module)
  - Gradle-dependency modules with divergences:
      per divergent file in module              → -0.1 (capped at -5 per module)
  - JAR dependencies outdated (major gap)       → -0.15 per module (capped at -3)
  - JAR dependencies outdated (minor/patch gap) → -0.05 per module (capped at -1)
  - Custom modules — tier-based LOC penalty:
      micro  < 500 LOC                          →  -1
      small  500–2.000 LOC                      →  -4
      medium 2.000–8.000 LOC                    →  -9
      large  > 8.000 LOC                        → -16
      global cap                                → -35

Migratability labels:
  80–100  easy
  60–79   moderate
  40–59   hard
  0–39    very_hard
"""

from typing import Optional


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _parse_version(v):
    if not v:
        return ()
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def _version_gap(installed, latest) -> str:
    """Returns 'none', 'patch', 'minor', or 'major'."""
    iv = _parse_version(installed)
    lv = _parse_version(latest)
    if not iv or not lv or lv <= iv:
        return "none"
    if len(iv) >= 1 and len(lv) >= 1 and lv[0] > iv[0]:
        return "major"
    if len(iv) >= 2 and len(lv) >= 2 and lv[1] > iv[1]:
        return "minor"
    return "patch"


def _module_diff_penalty(modules: list, penalty_per_file: float, cap: float) -> float:
    total = 0.0
    for m in modules:
        diff = m.get("diff")
        if diff:
            total += min(diff.get("modified_files", 0) * penalty_per_file, cap)
    return total


def compute_score(report: dict) -> dict:
    """
    Receives the full report dict (before score is populated) and returns:
      {"migration_score": int, "migratability": str, "score_breakdown": {...}}
    """
    score = 100.0
    breakdown = {}

    # --- Platform penalty ---
    platform_type = report.get("platform", {}).get("type", "etendo")
    if platform_type == "openbravo":
        score -= 20
        breakdown["openbravo_platform"] = -20
    else:
        breakdown["openbravo_platform"] = 0

    # --- Core divergences ---
    core = report.get("core_divergences", {})
    core_penalty = 0.0

    modified_files = core.get("modified_files") or 0
    files_penalty = _clamp(modified_files * 0.5, 0, 25)
    core_penalty += files_penalty

    diff_lines = (core.get("diff_lines_added") or 0) + (core.get("diff_lines_removed") or 0)
    lines_penalty = _clamp((diff_lines / 100) * 0.5, 0, 15)
    core_penalty += lines_penalty

    score -= core_penalty
    breakdown["core_divergences"] = round(-core_penalty, 2) or 0

    # --- Local not-maintained modules ---
    not_maintained = report.get("modules", {}).get("local_not_maintained", [])
    nm_penalty = _clamp(len(not_maintained) * 3, 0, 20)
    score -= nm_penalty
    breakdown["local_not_maintained"] = round(-nm_penalty, 2)

    # --- Custom modules — tier-based LOC penalty ---
    _TIER_PENALTY = {"micro": 1, "small": 4, "medium": 9, "large": 16}
    custom = report.get("modules", {}).get("custom", [])
    custom_penalty = 0.0
    custom_detail = []
    for m in custom:
        tier_key = (m.get("custom_size") or {}).get("key", "medium")
        tier_label = (m.get("custom_size") or {}).get("label", "desconocido")
        loc = m.get("line_count", 0)
        pen = _TIER_PENALTY.get(tier_key, 9)
        custom_penalty += pen
        custom_detail.append({
            "java_package": m["java_package"],
            "line_count": loc,
            "size_tier": tier_key,
            "size_label": tier_label,
            "penalty": -pen,
        })
    custom_penalty = _clamp(custom_penalty, 0, 35)
    score -= custom_penalty
    breakdown["custom_modules"] = round(-custom_penalty, 2) or 0
    breakdown["custom_modules_detail"] = custom_detail

    # --- Local maintained modules with divergences ---
    local_maintained = report.get("modules", {}).get("local_maintained", [])
    em_penalty = _module_diff_penalty(local_maintained, 0.2, 10)
    score -= em_penalty
    breakdown["local_maintained_divergences"] = round(-em_penalty, 2) or 0

    # --- Gradle source modules with divergences ---
    gradle_source = report.get("modules", {}).get("gradle_source", [])
    gd_penalty = _module_diff_penalty(gradle_source, 0.1, 5)
    score -= gd_penalty
    breakdown["gradle_source_divergences"] = round(-gd_penalty, 2) or 0

    # --- JAR dependencies — penalize only for version gap ---
    jar_deps = report.get("modules", {}).get("gradle_jar", [])
    jar_major = jar_minor = 0
    for m in jar_deps:
        gap = _version_gap(m.get("version"), m.get("latest_version"))
        if gap == "major":
            jar_major += 1
        elif gap in ("minor", "patch"):
            jar_minor += 1
    jar_penalty = _clamp(jar_major * 0.15, 0, 3) + _clamp(jar_minor * 0.05, 0, 1)
    score -= jar_penalty
    breakdown["jar_dependency_outdated"] = round(-jar_penalty, 2) or 0

    final_score = max(0, round(score))

    if final_score >= 80:
        label = "easy"
    elif final_score >= 60:
        label = "moderate"
    elif final_score >= 40:
        label = "hard"
    else:
        label = "very_hard"

    return {
        "migration_score": final_score,
        "migratability": label,
        "score_breakdown": breakdown,
    }
