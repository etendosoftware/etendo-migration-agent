"""
core_diff.py — Detects customizations/divergences in Etendo core source folders.

Compares the client installation against the latest clean Etendo base (zip).
The diff captures both customizations and version gaps — both are migration obstacles.

Source folders analyzed:
  src, src-db, src-core, src-wad, modules_core, src-trl, src-util

Strategy:
  1. Locate the latest etendo-core-*.zip in data/etendo-base/
  2. Extract it to a temp directory
  3. Compare file by file using difflib
  4. Report modified, added and deleted files with line counts
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


def analyze_core(etendo_root: str, **_) -> dict:
    """
    Compares client source folders against the latest clean Etendo base.

    Returns:
      {
        "status":            "clean" | "modified" | "no_base",
        "base_version":      "25.4.11" | None,
        "folders_checked":   [...],
        "modified_files":    int,
        "added_files":       int,
        "deleted_files":     int,
        "diff_lines_added":  int,
        "diff_lines_removed": int,
        "files":             [{"path", "status", "lines_added", "lines_removed"}]
      }
    """
    base_zip = _find_base_zip()
    if not base_zip:
        return {
            "status": "no_base",
            "base_version": None,
            "folders_checked": [],
            "modified_files": None,
            "added_files": None,
            "deleted_files": None,
            "diff_lines_added": None,
            "diff_lines_removed": None,
            "files": [],
        }

    base_version = base_zip.stem.replace("etendo-core-", "")
    folders = [f for f in SOURCE_FOLDERS if os.path.isdir(os.path.join(etendo_root, f))]

    with tempfile.TemporaryDirectory() as tmp:
        # Extract only the relevant folders from the zip
        with zipfile.ZipFile(base_zip) as zf:
            members = [
                m for m in zf.namelist()
                if any(m.startswith(f + "/") or m == f for f in folders)
            ]
            zf.extractall(tmp, members=members)

        base_root = tmp
        files = []
        total_added = total_removed = 0
        modified = added = deleted = 0

        for folder in folders:
            client_folder = os.path.join(etendo_root, folder)
            base_folder = os.path.join(base_root, folder)

            # Walk base files — detect modified and deleted
            for dirpath, _, filenames in os.walk(base_folder):
                for filename in filenames:
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
        "status": "modified" if files else "clean",
        "base_version": base_version,
        "folders_checked": folders,
        "modified_files": modified,
        "added_files": added,
        "deleted_files": deleted,
        "diff_lines_added": total_added,
        "diff_lines_removed": total_removed,
        "files": files,
    }
