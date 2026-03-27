"""
migration_scorer.py — Calculates a migration score and migratability label.

Score: 0–100 (higher = easier to migrate to SaaS)

All penalties are based on volume of custom code (LOC / diff lines),
NOT on file counts.

Penalties applied:
  - Platform is Openbravo (not Etendo)              → -20

  - Core divergences (diff lines added+removed):
      < 1.000 lines                                  →  -5
      1.000 – 5.000 lines                            → -12
      5.000 – 20.000 lines                           → -20
      > 20.000 lines                                 → -25 (cap)

  - Local not-maintained modules                     → -3 per module (cap -20)

  - Custom modules — tier-based LOC penalty:
      micro  < 500 LOC                               →  -1
      small  500 – 2.000 LOC                         →  -4
      medium 2.000 – 8.000 LOC                       →  -9
      large  > 8.000 LOC                             → -16
      global cap                                     → -35

  - Local maintained modules with custom code
    (diff lines per module):
      0 – 50 lines    (noise / formatting)           →   0
      50 – 200 lines                                 →  -1
      200 – 1.000 lines                              →  -3
      1.000 – 5.000 lines                            →  -6
      > 5.000 lines                                  → -10
      global cap across all maintained modules       → -15

NOT penalized (easy to resolve via update):
  - Gradle source modules with divergences           →   0
  - JAR dependencies outdated                        →   0

Migratability labels:
  80–100  easy
  60–79   moderate
  40–59   hard
  0–39    very_hard
"""


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _core_lines_penalty(diff_lines: int) -> float:
    if diff_lines < 1_000:
        return 5.0
    if diff_lines < 5_000:
        return 12.0
    if diff_lines < 20_000:
        return 20.0
    return 25.0


def _maintained_module_penalty(diff_lines: int) -> float:
    if diff_lines <= 50:
        return 0.0
    if diff_lines <= 200:
        return 1.0
    if diff_lines <= 1_000:
        return 3.0
    if diff_lines <= 5_000:
        return 6.0
    return 10.0


def compute_score(report: dict) -> dict:
    """
    Receives the full report dict and returns:
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

    # --- Core divergences (line-based) ---
    core = report.get("core_divergences", {})
    diff_lines = (core.get("diff_lines_added") or 0) + (core.get("diff_lines_removed") or 0)
    core_penalty = _core_lines_penalty(diff_lines) if core.get("status") == "modified" else 0.0
    score -= core_penalty
    breakdown["core_divergences"] = round(-core_penalty, 2) or 0
    breakdown["core_diff_lines"] = diff_lines

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

    # --- Local maintained modules — line-based penalty, global cap -15 ---
    local_maintained = report.get("modules", {}).get("local_maintained", [])
    em_penalty = 0.0
    for m in local_maintained:
        diff = m.get("diff") or {}
        lines = (diff.get("diff_lines_added") or 0) + (diff.get("diff_lines_removed") or 0)
        em_penalty += _maintained_module_penalty(lines)
    em_penalty = _clamp(em_penalty, 0, 15)
    score -= em_penalty
    breakdown["local_maintained_divergences"] = round(-em_penalty, 2) or 0

    # --- Gradle source modules — no penalty (outdated != customized) ---
    breakdown["gradle_source_divergences"] = 0

    # --- JAR dependencies — no penalty (JARs are a positive signal) ---
    breakdown["jar_dependency_outdated"] = 0

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
