"""
module_diff.py — Compares client modules against the latest clean Etendo modules base.

For each module present in the client's /modules directory that is an Etendo-maintained
module (found in etendo-modules-latest.zip), performs a file-by-file diff and reports:
  - lines added / removed (customization or version gap metric)
  - files modified, added, deleted

Modules not found in the base zip are skipped here (handled by module_classifier as
not_maintained or custom).
"""

import difflib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

MODULES_BASE_ZIP = Path(__file__).parent.parent / "data" / "modules-base" / "etendo-modules-latest.zip"

TEXT_EXTENSIONS = {
    ".java", ".xml", ".sql", ".properties", ".gradle", ".js", ".css",
    ".html", ".jrxml", ".javaxml", ".py", ".sh", ".txt", ".md",
}


def _is_text_file(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def _read_lines(filepath: str) -> list:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def _count_diff_lines(base_lines: list, client_lines: list) -> tuple:
    added = removed = 0
    for line in difflib.ndiff(base_lines, client_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def _modules_in_zip(zf: zipfile.ZipFile) -> set:
    """Returns the set of module java_packages present in the zip."""
    modules = set()
    for name in zf.namelist():
        parts = name.split("/")
        if len(parts) >= 2 and parts[0] == "modules" and parts[1]:
            modules.add(parts[1])
    return modules


def analyze_module(java_package: str, module_path: str, base_root: str) -> dict:
    """
    Compares a single client module against its clean base.

    Args:
        java_package: e.g. 'com.etendoerp.bankingpool'
        module_path:  absolute path to the module in the client installation
        base_root:    path to the extracted modules-base directory

    Returns diff summary for this module.
    """
    base_module_path = os.path.join(base_root, "modules", java_package)
    if not os.path.isdir(base_module_path):
        return None

    files = []
    total_added = total_removed = 0
    modified = added = deleted = 0

    # Walk base files — detect modified and deleted
    for dirpath, _, filenames in os.walk(base_module_path):
        for filename in filenames:
            base_file = os.path.join(dirpath, filename)
            rel = os.path.relpath(base_file, base_module_path)
            client_file = os.path.join(module_path, rel)

            if not os.path.exists(client_file):
                deleted += 1
                files.append({"path": rel, "status": "deleted", "lines_added": 0, "lines_removed": 0})
                continue

            if not _is_text_file(filename):
                continue

            base_lines = _read_lines(base_file)
            client_lines = _read_lines(client_file)

            if base_lines == client_lines:
                continue

            la, lr = _count_diff_lines(base_lines, client_lines)
            total_added += la
            total_removed += lr
            modified += 1
            files.append({"path": rel, "status": "modified", "lines_added": la, "lines_removed": lr})

    # Walk client files — detect added
    for dirpath, _, filenames in os.walk(module_path):
        for filename in filenames:
            client_file = os.path.join(dirpath, filename)
            rel = os.path.relpath(client_file, module_path)
            base_file = os.path.join(base_module_path, rel)

            if not os.path.exists(base_file):
                la = len(_read_lines(client_file)) if _is_text_file(filename) else 0
                total_added += la
                added += 1
                files.append({"path": rel, "status": "added", "lines_added": la, "lines_removed": 0})

    return {
        "modified_files": modified,
        "added_files": added,
        "deleted_files": deleted,
        "diff_lines_added": total_added,
        "diff_lines_removed": total_removed,
        "files": files,
    }


def analyze_modules_diff(etendo_root: str, modules_to_diff: list) -> dict:
    """
    Runs diff for a list of modules against the clean base zip.

    Args:
        etendo_root:     root of the client installation
        modules_to_diff: list of module dicts from module_classifier
                         (must have 'java_package' and 'path')

    Returns:
        {java_package: diff_result, ...}
    """
    if not MODULES_BASE_ZIP.exists() or not modules_to_diff:
        return {}

    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        # Extract only the modules we need (normalize to lowercase to match zip entries)
        needed = {m["java_package"].lower() for m in modules_to_diff}

        with zipfile.ZipFile(MODULES_BASE_ZIP) as zf:
            available = _modules_in_zip(zf)
            to_extract = needed & available
            members = [
                m for m in zf.namelist()
                if len(m.split("/")) > 1 and m.split("/")[1] in to_extract
            ]
            zf.extractall(tmp, members=members)

        for module in modules_to_diff:
            jp = module["java_package"]
            jp_lower = jp.lower()
            if jp_lower not in available:
                continue
            diff = analyze_module(jp_lower, module["path"], tmp)
            if diff is not None:
                results[jp] = diff

    return results
