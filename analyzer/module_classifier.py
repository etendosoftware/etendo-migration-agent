"""
module_classifier.py — Classifies modules found in the installation.

Categories:
  - jar_dependencies:    resolved from build.gradle as JARs in build/etendo/modules/
                         (best case: migrate by bumping version in build.gradle)
  - gradle_dependencies: bundle declared in build.gradle AND source present in modules/
  - etendo_maintained:   in supported_modules.json but bundle not a gradle dependency
  - not_maintained:      not in supported_modules.json and not custom
  - custom:              any segment of java_package is "custom"/"customization"
                         or contains the client name slug
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

SUPPORTED_MODULES_PATH = Path(__file__).parent.parent / "data" / "supported_modules.json"
JAR_MODULES_DIR = os.path.join("build", "etendo", "modules")


def _load_supported_modules() -> dict:
    """Returns {java_package: {bundle, git_url, latest_version}} from supported_modules.json."""
    if not SUPPORTED_MODULES_PATH.exists():
        return {}
    with open(SUPPORTED_MODULES_PATH) as f:
        data = json.load(f)
    return {m["java_package"]: m for m in data.get("modules", [])}


def _parse_gradle_bundles(etendo_root: str) -> set:
    """
    Parses build.gradle and returns all declared bundle java_packages.
    Format: 'com.etendoerp:financial.extensions:[...]'
    Reconstructed as: com.etendoerp.financial.extensions
    Group is always 2 segments, artifact is the rest.
    """
    gradle_path = os.path.join(etendo_root, "build.gradle")
    declared = set()
    if not os.path.exists(gradle_path):
        return declared

    pattern = re.compile(
        r"['\"]([a-z][a-z0-9]*\.[a-z][a-z0-9]*):([a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)*):[^'\"]+['\"]"
    )
    with open(gradle_path, errors="replace") as f:
        for line in f:
            for m in pattern.finditer(line):
                declared.add(f"{m.group(1)}.{m.group(2)}")
    return declared


def _read_module_metadata(module_path: str) -> dict:
    """Reads name, version, author from src-db/database/sourcedata/AD_MODULE.xml."""
    xml_path = os.path.join(module_path, "src-db", "database", "sourcedata", "AD_MODULE.xml")
    if not os.path.exists(xml_path):
        return {}
    try:
        tree = ET.parse(xml_path)
        node = tree.getroot().find("AD_MODULE")
        if node is None:
            return {}
        def t(tag):
            el = node.find(tag)
            return el.text.strip() if el is not None and el.text else None
        return {
            "name":    t("NAME"),
            "version": t("VERSION"),
            "author":  t("AUTHOR"),
        }
    except ET.ParseError:
        return {}


def _client_slug(client_name: str) -> Optional[str]:
    """Converts client name to a lowercase slug for matching in java_packages."""
    slug = re.sub(r"[^a-z0-9]", "", client_name.lower())
    return slug if len(slug) >= 3 else None


def _is_custom(java_package: str, client_slug: Optional[str]) -> bool:
    segments = java_package.lower().split(".")
    if any(s in ("custom", "customization") for s in segments):
        return True
    if client_slug and any(client_slug in s for s in segments):
        return True
    return False


def _scan_jar_modules(etendo_root: str, supported: dict, already_classified: set) -> list:
    """
    Scans build/etendo/modules/ for JAR-resolved modules.
    Skips any module already classified from /modules/ to avoid duplicates.

    Returns list of module dicts with category 'jar_dependencies'.
    """
    jar_dir = os.path.join(etendo_root, JAR_MODULES_DIR)
    if not os.path.isdir(jar_dir):
        return []

    results = []
    for entry in sorted(os.scandir(jar_dir), key=lambda e: e.name):
        if not entry.is_dir():
            continue

        java_package = entry.name
        java_package_lower = java_package.lower()

        if java_package_lower in already_classified:
            continue

        metadata = _read_module_metadata(entry.path)
        sup = supported.get(java_package_lower, {})

        module = {
            "java_package": java_package,
            "path": entry.path,
            "latest_version": sup.get("latest_version"),
            "bundle": sup.get("bundle", ""),
            "git_url": sup.get("git_url"),
            **metadata,
        }
        results.append(module)

    return results


def classify_modules(etendo_root: str, client_name: str) -> dict:
    """
    Scans modules/ (source) and build/etendo/modules/ (JAR) and classifies each module.

    Returns:
      {
        "gradle_jar":          [...],  # JARs resolved by Gradle — best migration scenario
        "gradle_source":       [...],  # source in /modules/ + bundle in build.gradle
        "local_maintained":    [...],  # source in /modules/ + in supported_modules.json
        "local_not_maintained":[...],  # source in /modules/ + unknown
        "custom":              [...],  # custom modules in /modules/
      }
    """
    results = {
        "gradle_jar":           [],
        "gradle_source":        [],
        "local_maintained":     [],
        "local_not_maintained": [],
        "custom":               [],
    }

    supported = _load_supported_modules()
    gradle_bundles = _parse_gradle_bundles(etendo_root)
    slug = _client_slug(client_name)

    # ── Scan /modules/ (source) ──────────────────────────────────────────────
    modules_dir = os.path.join(etendo_root, "modules")
    classified_from_source = set()

    if os.path.isdir(modules_dir):
        for entry in sorted(os.scandir(modules_dir), key=lambda e: e.name):
            if not entry.is_dir():
                continue

            java_package = entry.name
            java_package_lower = java_package.lower()
            classified_from_source.add(java_package_lower)
            metadata = _read_module_metadata(entry.path)

            module = {
                "java_package": java_package,
                "path": entry.path,
                **metadata,
            }

            if _is_custom(java_package, slug):
                results["custom"].append(module)
            elif java_package_lower in gradle_bundles:
                module["bundle"] = java_package_lower
                module["latest_version"] = supported.get(java_package_lower, {}).get("latest_version")
                results["gradle_source"].append(module)
            elif java_package_lower in supported:
                bundle = supported[java_package_lower].get("bundle", "")
                module["bundle"] = bundle
                module["git_url"] = supported[java_package_lower].get("git_url")
                module["latest_version"] = supported[java_package_lower].get("latest_version")
                if bundle in gradle_bundles:
                    results["gradle_source"].append(module)
                else:
                    results["local_maintained"].append(module)
            else:
                results["local_not_maintained"].append(module)

    # ── Scan build/etendo/modules/ (JARs) ───────────────────────────────────
    results["gradle_jar"] = _scan_jar_modules(
        etendo_root, supported, classified_from_source
    )

    return results
