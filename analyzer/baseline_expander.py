"""
baseline_expander.py — Generates a dynamic build.gradle and runs ./gradlew expand
to obtain the exact source of the installed module versions as a diff baseline.

This produces a baseline that matches the client's installed versions exactly,
so the subsequent diff measures only real customizations — not version gaps.

Strategy:
  1. Read githubUser / githubToken from the client's gradle.properties
     (or accept --github-token / --github-user from CLI)
  2. Detect the Etendo Gradle plugin version from the client's build.gradle
  3. Collect all bundles to expand (gradle_source + local_maintained modules)
     and resolve the installed version of each bundle
  4. Generate a minimal build.gradle + gradle.properties in a temp directory
  5. Copy the Gradle wrapper from the client installation
  6. Run `echo Y | ./gradlew expand` (non-interactive)
  7. Return the path to the temp directory, which now contains:
       modules/<java_package>/   — expanded module sources
       src/, src-db/, ...        — expanded core sources
"""

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


# ── credential helpers ────────────────────────────────────────────────────────

def _read_gradle_properties(etendo_root: str) -> dict:
    path = os.path.join(etendo_root, "gradle.properties")
    props = {}
    if not os.path.exists(path):
        return props
    with open(path, errors="replace") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
    return props


def read_github_credentials(etendo_root: str) -> tuple:
    """Returns (github_user, github_token) from gradle.properties, or (None, None)."""
    props = _read_gradle_properties(etendo_root)
    return props.get("githubUser"), props.get("githubToken")


# ── plugin version detection ──────────────────────────────────────────────────

def _detect_plugin_version(etendo_root: str) -> str:
    """Reads the com.etendoerp.gradleplugin version from build.gradle."""
    gradle_path = os.path.join(etendo_root, "build.gradle")
    default = "2.2.1"
    if not os.path.exists(gradle_path):
        return default
    pattern = re.compile(r"com\.etendoerp\.gradleplugin['\"\s]+version\s+['\"]([^'\"]+)['\"]")
    with open(gradle_path, errors="replace") as f:
        content = f.read()
    m = pattern.search(content)
    return m.group(1) if m else default


# ── bundle version resolution ─────────────────────────────────────────────────

def _read_module_version(module_path: str) -> Optional[str]:
    xml_path = os.path.join(module_path, "src-db", "database", "sourcedata", "AD_MODULE.xml")
    if not os.path.exists(xml_path):
        return None
    try:
        root = ET.parse(xml_path).getroot()
        node = root.find("AD_MODULE")
        if node is None:
            return None
        el = node.find("VERSION")
        return el.text.strip() if el is not None and el.text else None
    except ET.ParseError:
        return None


def resolve_bundle_versions(etendo_root: str, modules: dict) -> dict:
    """
    Returns {bundle_java_package: version} for all bundles needed.

    Looks for the bundle module in:
      1. <etendo_root>/modules/<bundle>/
      2. <etendo_root>/build/etendo/modules/<bundle>/
    Falls back to the version of any of the bundle's child modules.
    """
    bundle_versions = {}
    all_modules = modules.get("gradle_source", []) + modules.get("local_maintained", [])

    # Build a map: bundle → list of (child_version, child_path)
    bundle_children: dict = {}
    for m in all_modules:
        bundle = m.get("bundle") or m["java_package"]
        bundle_children.setdefault(bundle, [])
        bundle_children[bundle].append(m)

    for bundle, children in bundle_children.items():
        # Try to find the bundle module itself
        version = None
        for search_root in [
            os.path.join(etendo_root, "modules", bundle),
            os.path.join(etendo_root, "build", "etendo", "modules", bundle),
        ]:
            if os.path.isdir(search_root):
                version = _read_module_version(search_root)
                if version:
                    break

        # Fall back to first child's version
        if not version and children:
            version = children[0].get("version")

        if version:
            bundle_versions[bundle] = version

    return bundle_versions


# ── build.gradle generation ───────────────────────────────────────────────────

def _artifact_from_bundle(bundle_package: str) -> str:
    """
    Converts bundle java_package to Gradle group:artifact.
    Group = first 2 segments, artifact = rest.
    e.g. com.etendoerp.financial.extensions → com.etendoerp:financial.extensions
    """
    parts = bundle_package.split(".")
    group = ".".join(parts[:2])
    artifact = ".".join(parts[2:])
    return f"{group}:{artifact}"


def generate_build_gradle(
    core_version: str,
    plugin_version: str,
    bundle_versions: dict,
) -> str:
    """Generates the content of the dynamic build.gradle."""
    deps = ""
    for bundle, version in sorted(bundle_versions.items()):
        coord = _artifact_from_bundle(bundle)
        deps += f"    moduleDeps('{coord}:{version}@zip'){{transitive=true}}\n"

    # Pin core to exact version using a tight range
    core_range = f"[{core_version},{core_version}]"

    return f"""plugins {{
    id 'java'
    id 'com.etendoerp.gradleplugin' version '{plugin_version}'
}}

etendo {{
    coreVersion = "{core_range}"
    supportJars = false
    forceResolution = true
}}

dependencies {{
{deps}}}
"""


def generate_gradle_properties(
    github_user: str,
    github_token: str,
    extra_props: dict = None,
) -> str:
    """
    Generates gradle.properties merging the client's original properties with
    the required overrides. This ensures plugin-required properties like
    nexusUser are present even if empty.
    """
    # Start from client properties (excluding daemon/jvm settings we override)
    _SKIP = {"org.gradle.jvmargs", "org.gradle.daemon", "githubUser", "githubToken"}
    lines = []
    if extra_props:
        for k, v in extra_props.items():
            if k not in _SKIP:
                lines.append(f"{k}={v}")

    # Always set these (increase heap to avoid OOM during expand)
    lines += [
        f"githubUser={github_user}",
        f"githubToken={github_token}",
        "org.gradle.jvmargs=-Xmx6g -Dfile.encoding=UTF-8",
        "org.gradle.daemon=false",
    ]
    return "\n".join(lines) + "\n"


def generate_settings_gradle(github_user: str, github_token: str) -> str:
    """Generates a settings.gradle that configures the Etendo plugin repository."""
    return f"""pluginManagement {{
    repositories {{
        mavenCentral()
        gradlePluginPortal()
        maven {{
            url = 'https://maven.pkg.github.com/etendosoftware/com.etendoerp.gradleplugin'
            credentials {{
                username = "{github_user}"
                password = "{github_token}"
            }}
        }}
        maven {{
            url = 'https://repo.futit.cloud/repository/maven-public-snapshots'
        }}
    }}
}}

rootProject.name = "etendo-baseline"
"""


# ── gradle wrapper copy ───────────────────────────────────────────────────────

def _copy_gradle_wrapper(etendo_root: str, target_dir: str) -> bool:
    """Copies gradlew + gradle/ from the client installation to target_dir."""
    gradlew_src = os.path.join(etendo_root, "gradlew")
    gradle_dir_src = os.path.join(etendo_root, "gradle")

    if not os.path.exists(gradlew_src) or not os.path.isdir(gradle_dir_src):
        return False

    shutil.copy2(gradlew_src, os.path.join(target_dir, "gradlew"))
    os.chmod(os.path.join(target_dir, "gradlew"), 0o755)
    shutil.copytree(gradle_dir_src, os.path.join(target_dir, "gradle"))
    return True


# ── main entry point ──────────────────────────────────────────────────────────

def expand_baseline(
    etendo_root: str,
    modules: dict,
    core_version: str,
    github_user: Optional[str] = None,
    github_token: Optional[str] = None,
    work_dir: Optional[str] = None,
    verbose: bool = False,
) -> Optional[str]:
    """
    Runs ./gradlew expand in a temp directory configured to match the client's
    installed versions. Returns the path to the expanded directory, or None on failure.

    Args:
        etendo_root:   path to client installation
        modules:       classified modules dict (from module_classifier)
        core_version:  installed core version string (e.g. "24.2.6")
        github_user:   GitHub username (overrides gradle.properties)
        github_token:  GitHub token (overrides gradle.properties)
        work_dir:      optional directory to use instead of a temp dir (not cleaned up)
        verbose:       print gradlew output
    """
    # Resolve credentials and all client properties
    client_props = _read_gradle_properties(etendo_root)
    github_user  = github_user  or client_props.get("githubUser")
    github_token = github_token or client_props.get("githubToken")

    if not github_user or not github_token:
        print("WARNING: No GitHub credentials found. Skipping baseline expansion.")
        return None

    if not core_version:
        print("WARNING: Core version unknown. Skipping baseline expansion.")
        return None

    plugin_version  = _detect_plugin_version(etendo_root)
    bundle_versions = resolve_bundle_versions(etendo_root, modules)

    if not bundle_versions:
        print("WARNING: No bundles to expand. Skipping baseline expansion.")
        return None

    # Set up working directory
    cleanup = work_dir is None
    target = work_dir or tempfile.mkdtemp(prefix="etendo-baseline-")

    try:
        # Write build files
        with open(os.path.join(target, "build.gradle"), "w") as f:
            f.write(generate_build_gradle(core_version, plugin_version, bundle_versions))

        with open(os.path.join(target, "gradle.properties"), "w") as f:
            f.write(generate_gradle_properties(github_user, github_token, extra_props=client_props))

        with open(os.path.join(target, "settings.gradle"), "w") as f:
            f.write(generate_settings_gradle(github_user, github_token))

        # Copy Gradle wrapper from client
        if not _copy_gradle_wrapper(etendo_root, target):
            print("WARNING: Gradle wrapper not found in client installation.")
            return None

        if verbose:
            print(f"  Expanding baseline in: {target}")
            print(f"  Core version: {core_version}  Plugin: {plugin_version}")
            print(f"  Bundles: {len(bundle_versions)}")
            print()
            print("  ── build.gradle ─────────────────────────────────────────")
            build_gradle_content = open(os.path.join(target, "build.gradle")).read()
            for line in build_gradle_content.splitlines():
                print(f"  {line}")
            print("  ─────────────────────────────────────────────────────────")
            print()

        # Run expandCore and expandModules as separate invocations so that
        # each task gets its own 'yes Y' pipe for interactive confirmations.
        # GRADLE_OPTS sets heap for the Gradle client process (not the daemon).
        env = os.environ.copy()
        env["GRADLE_OPTS"] = "-Xmx6g -Dfile.encoding=UTF-8"
        info_flag = " --info" if verbose else ""

        for task in ("expandCore", "expandModules"):
            step_cmd = f"yes Y | ./gradlew {task}{info_flag}"
            step = subprocess.run(
                ["bash", "-c", step_cmd],
                cwd=target,
                capture_output=not verbose,
                timeout=600,
                env=env,
            )
            if step.returncode != 0:
                if not verbose and step.stderr:
                    print(f"WARNING: gradlew {task} failed:\n{step.stderr[-2000:]}")
                return None

        return target

    except subprocess.TimeoutExpired:
        print("WARNING: gradlew expand timed out (10 min).")
        return None
    except Exception as e:
        print(f"WARNING: baseline expansion error: {e}")
        return None
    finally:
        # Only clean up if we created the temp dir AND expansion failed
        # (caller is responsible for cleanup on success when work_dir is None)
        pass
