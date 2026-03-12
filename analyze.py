#!/usr/bin/env python3
"""
analyze.py — Etendo Migration Agent
Analyzes an Etendo/Openbravo installation and generates a migration report.

Usage:
    python3 analyze.py --path /opt/etendo --client "Acme Corp" --output report.json
"""

import argparse
import json
import os
import socket
import sys
from pathlib import Path

from analyzer.version_detector import detect_version
from analyzer.module_classifier import classify_modules
from analyzer.core_diff import analyze_core
from analyzer.module_diff import analyze_modules_diff
from analyzer.migration_scorer import compute_score


def parse_args():
    parser = argparse.ArgumentParser(
        description="Etendo Migration Agent — analyzes an installation and estimates migration effort"
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Absolute path to the Etendo/Openbravo installation root",
    )
    parser.add_argument(
        "--client",
        required=True,
        help="Client name (e.g. 'Acme Corp')",
    )
    parser.add_argument(
        "--output",
        default="report.json",
        help="Output file path for the JSON report (default: report.json)",
    )
    return parser.parse_args()


_TEXT_EXTENSIONS = {
    ".java", ".xml", ".sql", ".properties", ".gradle", ".js", ".css",
    ".html", ".jrxml", ".py", ".sh", ".txt", ".md",
}

_CUSTOM_SIZE_TIERS = [
    (500,  "micro",  "< 500 LOC"),
    (2000, "small",  "500–2.000 LOC"),
    (8000, "medium", "2.000–8.000 LOC"),
]


def _count_module_lines(module_path: str) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(module_path):
        for filename in filenames:
            if Path(filename).suffix.lower() in _TEXT_EXTENSIONS:
                try:
                    with open(os.path.join(dirpath, filename), encoding="utf-8", errors="replace") as f:
                        total += sum(1 for _ in f)
                except OSError:
                    pass
    return total


def _custom_size_tier(loc: int) -> dict:
    for threshold, key, label in _CUSTOM_SIZE_TIERS:
        if loc < threshold:
            return {"key": key, "label": label}
    return {"key": "large", "label": "> 8.000 LOC"}


def _build_modules(etendo_root: str, client: str) -> dict:
    modules = classify_modules(etendo_root, client)

    # Diff on gradle_source and local_maintained (source in /modules/)
    to_diff = modules["gradle_source"] + modules["local_maintained"]
    diffs = analyze_modules_diff(etendo_root, to_diff)
    for category in ("gradle_source", "local_maintained"):
        for m in modules[category]:
            if m["java_package"] in diffs:
                m["diff"] = diffs[m["java_package"]]

    # LOC + size tier for custom modules
    for m in modules["custom"]:
        loc = _count_module_lines(m["path"])
        m["line_count"] = loc
        m["custom_size"] = _custom_size_tier(loc)

    return modules


def build_report(client: str, etendo_root: str) -> dict:
    platform = detect_version(etendo_root)

    report = {
        "client": {
            "name": client,
            "hostname": socket.gethostname(),
        },
        "platform": platform,
        "modules": _build_modules(etendo_root, client),
        "core_divergences": analyze_core(etendo_root),
        "migration_score": None,
        "migratability": None,
        "score_breakdown": None,
    }

    scoring = compute_score(report)
    report["migration_score"] = scoring["migration_score"]
    report["migratability"] = scoring["migratability"]
    report["score_breakdown"] = scoring["score_breakdown"]

    return report


def main():
    args = parse_args()
    etendo_root = str(Path(args.path).resolve())

    if not Path(etendo_root).is_dir():
        print(f"ERROR: path '{etendo_root}' does not exist or is not a directory")
        sys.exit(1)

    print(f"Analyzing installation at: {etendo_root}")
    print(f"Client: {args.client}")

    report = build_report(client=args.client, etendo_root=etendo_root)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report saved to: {output_path}")
    print(f"Platform:          {report['platform']['type']} {report['platform']['version']}")
    print(f"Migration score:   {report['migration_score']}/100 ({report['migratability']})")
    modules = report["modules"]
    print(f"Modules — gradle_jar: {len(modules['gradle_jar'])}, "
          f"gradle_source: {len(modules['gradle_source'])}, "
          f"local_maintained: {len(modules['local_maintained'])}, "
          f"local_not_maintained: {len(modules['local_not_maintained'])}, "
          f"custom: {len(modules['custom'])}")
    core = report["core_divergences"]
    if core.get("status") == "modified":
        print(f"Core divergences:  {core['modified_files']} divergent, "
              f"{core['added_files']} added, {core['deleted_files']} deleted files")


if __name__ == "__main__":
    main()
