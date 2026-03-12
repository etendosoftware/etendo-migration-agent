"""
version_detector.py — Detects platform type and core version.

Platform detection:
  - Etendo:    has build.gradle in the root
  - Openbravo: no build.gradle

Version is read from AD_MODULE_ID=0 in src-db/database/sourcedata/AD_MODULE.xml.
"""

import os
import xml.etree.ElementTree as ET
from typing import Optional


CORE_MODULE_XML = os.path.join("src-db", "database", "sourcedata", "AD_MODULE.xml")


def detect_version(etendo_root: str) -> dict:
    """
    Returns:
      {
        "type":    "etendo" | "openbravo",
        "version": "25.4.0" | None,
      }
    """
    platform_type = _detect_platform(etendo_root)
    version = _read_core_version(etendo_root)

    return {
        "type": platform_type,
        "version": version,
    }


def _detect_platform(etendo_root: str) -> str:
    has_gradle = os.path.isfile(os.path.join(etendo_root, "build.gradle"))
    return "etendo" if has_gradle else "openbravo"


def _read_core_version(etendo_root: str) -> Optional[str]:
    xml_path = os.path.join(etendo_root, CORE_MODULE_XML)
    if not os.path.exists(xml_path):
        return None

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        for module in root.findall("AD_MODULE"):
            module_id = module.findtext("AD_MODULE_ID", "").strip()
            if module_id == "0":
                return module.findtext("VERSION", "").strip() or None
    except ET.ParseError:
        return None

    return None
