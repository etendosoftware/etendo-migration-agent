"""
core_diff.py — Detects customizations/divergences in Etendo core source folders.

Compares the client installation against a clean Etendo base.
The diff captures both customizations and version gaps — both are migration obstacles.

Source folders analyzed:
  src, src-db, src-core, src-wad, modules_core, src-trl, src-util

Strategy (in order of preference):
  1. Use a pre-expanded baseline_dir (from baseline_expander) — most accurate:
     matches the client's exact installed versions.
  2. Fall back to the latest etendo-core-*.zip in data/etendo-base/.
"""

import difflib
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

SOURCE_FOLDERS = [
    "src",
    "src-db",
    "src-core",
    "src-wad",
    "modules_core",
    "src-trl",
    "src-util",
]

BASE_DIR = Path(__file__).parent.parent / "data" / "etendo-base"

TEXT_EXTENSIONS = {
    ".java", ".xml", ".sql", ".properties", ".gradle", ".js", ".css",
    ".html", ".jrxml", ".javaxml", ".py", ".sh", ".txt", ".md",
}

_IGNORE_FILENAMES = {"etendo.artifact.properties"}


def _find_base_zip() -> Optional[Path]:
    """Returns the latest etendo-core-*.zip found in data/etendo-base/."""
    if not BASE_DIR.exists():
        return None
    zips = sorted(BASE_DIR.glob("etendo-core-*.zip"), reverse=True)
    return zips[0] if zips else None


def _is_text_file(path: str) -> bool:
    return Path(path).suffix.lower() in TEXT_EXTENSIONS


def _read_lines(filepath: str) -> list:
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except OSError:
        return []


def _count_diff_lines(base_lines: list, client_lines: list) -> tuple:
    """Returns (lines_added, lines_removed) between base and client."""
    added = removed = 0
    for line in difflib.ndiff(base_lines, client_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def _run_diff(etendo_root: str, base_root: str, folders: list) -> dict:
    """Runs the file-by-file diff between base_root and etendo_root for the given folders."""
    files = []
    total_added = total_removed = 0
    modified = added = deleted = 0

    for folder in folders:
        client_folder = os.path.join(etendo_root, folder)
        base_folder = os.path.join(base_root, folder)

        if not os.path.isdir(base_folder):
            continue

        # Walk base files — detect modified and deleted
        for dirpath, _, filenames in os.walk(base_folder):
            for filename in filenames:
                if filename in _IGNORE_FILENAMES:
                    continue

                base_file = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(base_file, base_root)
                client_file = os.path.join(etendo_root, rel_path)

                if not os.path.exists(client_file):
                    deleted += 1
                    files.append({"path": rel_path, "status": "deleted", "lines_added": 0, "lines_removed": 0})
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
                files.append({"path": rel_path, "status": "modified", "lines_added": la, "lines_removed": lr})

        # Walk client files — detect added (not in base)
        if os.path.isdir(client_folder):
            for dirpath, _, filenames in os.walk(client_folder):
                for filename in filenames:
                    if filename in _IGNORE_FILENAMES:
                        continue

                    client_file = os.path.join(dirpath, filename)
                    rel_path = os.path.relpath(client_file, etendo_root)
                    base_file = os.path.join(base_root, rel_path)

                    if not os.path.exists(base_file):
                        client_lines = _read_lines(client_file) if _is_text_file(filename) else []
                        la = len(client_lines)
                        total_added += la
                        added += 1
                        files.append({"path": rel_path, "status": "added", "lines_added": la, "lines_removed": 0})

    return {
        "modified_files": modified,
        "added_files": added,
        "deleted_files": deleted,
        "diff_lines_added": total_added,
        "diff_lines_removed": total_removed,
        "files": files,
    }


def analyze_core(etendo_root: str, baseline_dir: Optional[str] = None, **_) -> dict:
    """
    Compares client source folders against a clean Etendo base.

    Args:
        etendo_root:  path to the client installation
        baseline_dir: optional pre-expanded baseline directory (from baseline_expander).
                      When provided, used directly instead of the static zip.
                      Falls back to the static zip if baseline_dir has no core folders.

    Returns:
      {
        "status":            "clean" | "modified" | "no_base",
        "base_version":      "25.4.11" | None,
        "baseline_type":     "expanded" | "zip" | None,
        "folders_checked":   [...],
        "modified_files":    int,
        "added_files":       int,
        "deleted_files":     int,
        "diff_lines_added":  int,
        "diff_lines_removed": int,
        "files":             [{"path", "status", "lines_added", "lines_removed"}]
      }
    """
    folders = [f for f in SOURCE_FOLDERS if os.path.isdir(os.path.join(etendo_root, f))]

    # ── Option 1: use pre-expanded baseline ──────────────────────────────────
    if baseline_dir and os.path.isdir(baseline_dir):
        has_core = any(
            os.path.isdir(os.path.join(baseline_dir, f)) for f in SOURCE_FOLDERS
        )
        if has_core:
            diff = _run_diff(etendo_root, baseline_dir, folders)
            return {
                "status": "modified" if diff["files"] else "clean",
                "base_version": "expanded",
                "baseline_type": "expanded",
                "folders_checked": folders,
                **diff,
            }

    # ── Option 2: fall back to static zip ────────────────────────────────────
    base_zip = _find_base_zip()
    if not base_zip:
        return {
            "status": "no_base",
            "base_version": None,
            "baseline_type": None,
            "folders_checked": [],
            "modified_files": None,
            "added_files": None,
            "deleted_files": None,
            "diff_lines_added": None,
            "diff_lines_removed": None,
            "files": [],
        }

    base_version = base_zip.stem.replace("etendo-core-", "")

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(base_zip) as zf:
            members = [
                m for m in zf.namelist()
                if any(m.startswith(f + "/") or m == f for f in folders)
            ]
            zf.extractall(tmp, members=members)

        diff = _run_diff(etendo_root, tmp, folders)

    return {
        "status": "modified" if diff["files"] else "clean",
        "base_version": base_version,
        "baseline_type": "zip",
        "folders_checked": folders,
        **diff,
    }
