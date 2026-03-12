#!/usr/bin/env python3
"""
etendo_diagnose.py - Herramienta de diagnóstico para instalaciones de Etendo ERP.

Analiza una instalación de Etendo para determinar:
- Versión instalada del producto
- Inventario y clasificación de módulos (core, extensión oficial, customización)
- Detección de alteraciones en código core y módulos oficiales
- Métricas de customización (tablas, columnas, ventanas, procesos, etc.)
- Mapeo de impacto funcional por áreas del ERP
- Estimación preliminar de esfuerzo de migración

Uso:
    cd /ruta/a/instalacion/etendo
    python3 etendo_diagnose.py [opciones]

Requisitos:
    - Python 3.6+
    - psycopg2 (opcional, para consultas a base de datos)
    - git (opcional, para detección de alteraciones)
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Intentar importar psycopg2
# ---------------------------------------------------------------------------
try:
    import psycopg2
    import psycopg2.extras
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
log = logging.getLogger("etendo_diagnose")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
KNOWN_OFFICIAL_AUTHORS = {
    "Openbravo S.L.U.",
    "Openbravo S.L.U",
    "Openbravo S.L.",
    "Futit Services S.L.",
    "Futit Services SL",
    "Etendo",
    "Etendo Software",
    "Etendo Software S.L.",
}

KNOWN_OFFICIAL_PACKAGE_PREFIXES = (
    "org.openbravo.",
    "com.etendoerp.",
    "com.smf.",
)

SOURCE_EXTENSIONS = {".java", ".js", ".ts", ".jsx", ".tsx", ".html", ".xml", ".jrxml", ".groovy"}
CODE_EXTENSIONS = {".java", ".js", ".ts", ".jsx", ".tsx", ".groovy"}

# Puntos para estimación de esfuerzo
EFFORT_WEIGHTS = {
    "custom_java_file": 2,
    "custom_loc_per_100": 1,
    "custom_table": 5,
    "custom_column_on_existing": 3,
    "custom_window": 1,
    "custom_tab": 0.5,
    "custom_process": 4,
    "custom_report": 4,
    "custom_field": 0.2,
    "modified_core_file": 10,
    "deleted_core_file": 8,
    "added_file_in_core": 6,
    "version_distance_major": 15,
}

EFFORT_BANDS = [
    (50, "Bajo", "~1-2 semanas"),
    (150, "Medio", "~3-6 semanas"),
    (400, "Alto", "~2-4 meses"),
    (float("inf"), "Muy Alto", "~4+ meses, considerar reimplementación"),
]

# Áreas funcionales embebidas (fallback si no existe functional_areas.json)
EMBEDDED_FUNCTIONAL_AREAS = {
    "finance": {
        "description": "Contabilidad, pagos, cobros, extractos bancarios",
        "packages": ["org.openbravo.financial", "com.etendoerp.financial",
                      "org.openbravo.advpaymentmngt", "com.etendoerp.advpaymentmngt"],
        "tables": ["C_INVOICE", "C_PAYMENT", "FIN_PAYMENT", "FIN_BANKSTATEMENT",
                    "FACT_ACCT", "C_GLJOURNAL", "C_DEBT_PAYMENT", "A_ASSET"],
        "windows": ["%invoice%", "%payment%", "%financial%", "%bank%", "%journal%"],
    },
    "sales": {
        "description": "Pedidos de venta, presupuestos",
        "packages": ["org.openbravo.sales", "com.etendoerp.sales"],
        "tables": ["C_ORDER", "C_ORDERLINE"],
        "windows": ["%sales%order%", "%quotation%"],
    },
    "procurement": {
        "description": "Compras, requisiciones",
        "packages": ["org.openbravo.procurement", "com.etendoerp.procurement"],
        "tables": ["M_REQUISITION"],
        "windows": ["%purchase%order%", "%requisition%"],
    },
    "warehouse": {
        "description": "Almacenes, inventario, movimientos",
        "packages": ["org.openbravo.warehouse", "com.etendoerp.warehouse"],
        "tables": ["M_INOUT", "M_MOVEMENT", "M_INVENTORY", "M_LOCATOR", "M_WAREHOUSE"],
        "windows": ["%warehouse%", "%shipment%", "%inventory%"],
    },
    "production": {
        "description": "Fabricación, planes de producción",
        "packages": ["org.openbravo.manufacturing", "com.etendoerp.production"],
        "tables": ["MA_PROCESSPLAN", "MA_WORKEFFORT"],
        "windows": ["%production%", "%manufacturing%"],
    },
    "master_data": {
        "description": "Terceros, productos, proyectos",
        "packages": [],
        "tables": ["C_BPARTNER", "M_PRODUCT", "C_PROJECT", "M_PRICELIST"],
        "windows": ["%business%partner%", "%product%", "%price%list%"],
    },
    "setup": {
        "description": "Configuración general, roles, alertas",
        "packages": ["org.openbravo.base", "org.openbravo.service"],
        "tables": ["AD_ORG", "AD_ROLE", "AD_USER"],
        "windows": ["%organization%", "%role%", "%user%"],
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# 1. EtendoInstallation – Descubrimiento de la instalación
# ═══════════════════════════════════════════════════════════════════════════

class EtendoInstallation:
    """Detecta y valida una instalación de Etendo, extrae configuración."""

    def __init__(self, root_path: str):
        self.root = Path(root_path).resolve()
        self.version = None
        self.version_label = None
        self.db_config = {}
        self.has_git = False
        self.git_branch = None

    def validate(self) -> bool:
        """Verifica que el directorio es una instalación válida de Etendo."""
        checks = [
            self.root / "build.gradle",
            self.root / "modules_core",
        ]
        missing = [str(c) for c in checks if not c.exists()]
        if missing:
            log.error("No se encontraron los siguientes elementos necesarios:")
            for m in missing:
                log.error(f"  - {m}")
            log.error("¿Estás ejecutando la herramienta en la raíz de una instalación de Etendo?")
            return False
        return True

    def detect_version(self):
        """Extrae la versión del producto de build.gradle."""
        build_gradle = self.root / "build.gradle"
        if build_gradle.exists():
            content = build_gradle.read_text(errors="replace")
            # Buscar CURRENT_VERSION
            m = re.search(r'(?:final\s+String\s+)?CURRENT_VERSION\s*=\s*["\']([^"\']+)', content)
            if m:
                self.version = m.group(1)
            # Buscar etendo.coreVersion
            m2 = re.search(r'coreVersion\s*=\s*["\']([^"\']+)', content)
            if m2 and not self.version:
                self.version = m2.group(1)
            # Buscar como dependencia
            m3 = re.search(r'etendo-core:([^\s"\')\]]+)', content)
            if m3 and not self.version:
                self.version = m3.group(1)

        # Intentar desde AD_MODULE.xml del core
        core_module_xml = self.root / "src-db" / "database" / "sourcedata" / "AD_MODULE.xml"
        if core_module_xml.exists():
            try:
                tree = ET.parse(str(core_module_xml))
                for module in tree.getroot():
                    mod_id = _xml_text(module, "AD_MODULE_ID")
                    if mod_id == "0":
                        v = _xml_text(module, "VERSION")
                        vl = _xml_text(module, "VERSION_LABEL")
                        if v and not self.version:
                            self.version = v
                        if vl:
                            self.version_label = vl
                        break
            except ET.ParseError:
                log.warning("No se pudo parsear AD_MODULE.xml del core")

        if not self.version:
            self.version = "desconocida"
            log.warning("No se pudo determinar la versión de Etendo")

    def detect_db_config(self):
        """Extrae la configuración de base de datos."""
        # Primero intentar Openbravo.properties
        props_path = self.root / "config" / "Openbravo.properties"
        if not props_path.exists():
            # Intentar gradle.properties
            props_path = self.root / "gradle.properties"

        if not props_path.exists():
            log.warning("No se encontró archivo de configuración de base de datos")
            return

        props = _parse_properties(str(props_path))

        # Extraer host y puerto de bbdd.url
        host = "localhost"
        port = 5432
        url = props.get("bbdd.url", "")
        m = re.search(r'jdbc:postgresql://([^:/]+)(?::(\d+))?', url)
        if m:
            host = m.group(1)
            if m.group(2):
                port = int(m.group(2))

        self.db_config = {
            "host": host,
            "port": port,
            "database": props.get("bbdd.sid", props.get("bbdd.databaseName", "")),
            "user": props.get("bbdd.user", ""),
            "password": props.get("bbdd.password", ""),
        }

    def detect_git(self):
        """Verifica si hay repositorio Git disponible."""
        git_dir = self.root / ".git"
        if not git_dir.exists():
            self.has_git = False
            return

        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, timeout=10,
                cwd=str(self.root),
            )
            self.has_git = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.has_git = False

        if self.has_git:
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(self.root),
                )
                self.git_branch = result.stdout.strip() if result.returncode == 0 else None
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

    def get_info(self) -> dict:
        return {
            "root_path": str(self.root),
            "version": self.version,
            "version_label": self.version_label,
            "has_git": self.has_git,
            "git_branch": self.git_branch,
            "db_configured": bool(self.db_config.get("database")),
        }


# ═══════════════════════════════════════════════════════════════════════════
# 2. ModuleScanner – Inventario de módulos
# ═══════════════════════════════════════════════════════════════════════════

class ModuleScanner:
    """Escanea y clasifica todos los módulos de la instalación."""

    def __init__(self, root: Path):
        self.root = root
        self.modules = []

    def scan(self):
        """Escanea modules_core/ y modules/."""
        self.modules = []

        # Escanear modules_core/
        core_dir = self.root / "modules_core"
        if core_dir.is_dir():
            for entry in sorted(core_dir.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    mod = self._parse_module(entry, "core")
                    if mod:
                        self.modules.append(mod)

        # Escanear modules/
        modules_dir = self.root / "modules"
        if modules_dir.is_dir():
            for entry in sorted(modules_dir.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    mod = self._parse_module(entry, "extension")
                    if mod:
                        self.modules.append(mod)

        log.info(f"Módulos encontrados: {len(self.modules)} "
                 f"(core: {sum(1 for m in self.modules if m['classification'] == 'core')}, "
                 f"oficial: {sum(1 for m in self.modules if m['classification'] == 'official_extension')}, "
                 f"custom: {sum(1 for m in self.modules if m['classification'] == 'custom')})")

    def _parse_module(self, module_dir: Path, location: str) -> dict | None:
        """Parsea un directorio de módulo y extrae metadata."""
        ad_module_xml = module_dir / "src-db" / "database" / "sourcedata" / "AD_MODULE.xml"

        info = {
            "directory": str(module_dir),
            "dir_name": module_dir.name,
            "location": location,
            "classification": "core" if location == "core" else "custom",
            "ad_module_id": None,
            "name": module_dir.name,
            "version": None,
            "java_package": module_dir.name,
            "type": None,
            "author": None,
            "license_type": None,
            "is_commercial": False,
            "description": None,
            "is_in_development": False,
            "has_source": False,
            "source_file_count": 0,
            "loc": 0,
        }

        if ad_module_xml.exists():
            try:
                tree = ET.parse(str(ad_module_xml))
                root_el = tree.getroot()
                # Puede haber múltiples registros; tomamos el primero
                module_el = root_el.find("AD_MODULE")
                if module_el is not None:
                    info["ad_module_id"] = _xml_text(module_el, "AD_MODULE_ID")
                    info["name"] = _xml_text(module_el, "NAME") or module_dir.name
                    info["version"] = _xml_text(module_el, "VERSION")
                    info["java_package"] = _xml_text(module_el, "JAVAPACKAGE") or module_dir.name
                    info["type"] = _xml_text(module_el, "TYPE")
                    info["author"] = _xml_text(module_el, "AUTHOR")
                    info["license_type"] = _xml_text(module_el, "LICENSETYPE")
                    info["is_commercial"] = _xml_text(module_el, "ISCOMMERCIAL") == "Y"
                    info["description"] = _xml_text(module_el, "DESCRIPTION")
                    info["is_in_development"] = _xml_text(module_el, "ISINDEVELOPMENT") == "Y"
            except ET.ParseError:
                log.warning(f"No se pudo parsear {ad_module_xml}")

        # Clasificar si es extension
        if location == "extension":
            info["classification"] = self._classify_extension(info)

        # Contar archivos fuente y líneas de código
        src_dir = module_dir / "src"
        if src_dir.is_dir():
            info["has_source"] = True
            file_count, loc = _count_source(src_dir)
            info["source_file_count"] = file_count
            info["loc"] = loc

        return info

    def _classify_extension(self, info: dict) -> str:
        """Clasifica un módulo de modules/ como oficial o custom."""
        author = (info.get("author") or "").strip()
        pkg = info.get("java_package") or ""

        # Autor conocido como oficial
        if author in KNOWN_OFFICIAL_AUTHORS:
            return "official_extension"

        # Prefijo de paquete conocido como oficial
        for prefix in KNOWN_OFFICIAL_PACKAGE_PREFIXES:
            if pkg.startswith(prefix):
                return "official_extension"

        return "custom"

    def get_by_classification(self, classification: str) -> list:
        return [m for m in self.modules if m["classification"] == classification]


# ═══════════════════════════════════════════════════════════════════════════
# 3. TamperingDetector – Detección de alteraciones
# ═══════════════════════════════════════════════════════════════════════════

class TamperingDetector:
    """Detecta modificaciones en código core y módulos oficiales."""

    def __init__(self, root: Path, has_git: bool, manifest_path: str | None = None):
        self.root = root
        self.has_git = has_git
        self.manifest_path = manifest_path
        self.findings = {
            "method": None,
            "core_changes": {},
            "official_changes": {},
            "summary": {
                "total_modified": 0,
                "total_added": 0,
                "total_deleted": 0,
            },
        }

    def detect(self, official_modules: list):
        """Ejecuta la detección de alteraciones."""
        if self.has_git:
            self._detect_with_git(official_modules)
        elif self.manifest_path:
            self._detect_with_manifest(official_modules)
        else:
            self.findings["method"] = "none"
            log.warning("No hay Git ni manifiesto disponible. "
                        "Detección de alteraciones no disponible.")
            log.warning("Use --manifest para proporcionar un archivo de checksums.")
            return

    def _detect_with_git(self, official_modules: list):
        """Usa Git para detectar cambios."""
        self.findings["method"] = "git"

        # Detectar cambios en modules_core/
        log.info("Analizando alteraciones en modules_core/ (vía Git)...")
        core_changes = self._git_changes("modules_core/")
        if core_changes:
            self.findings["core_changes"] = core_changes

        # Detectar cambios en src/ (código fuente principal)
        log.info("Analizando alteraciones en src/ (vía Git)...")
        src_changes = self._git_changes("src/")
        if src_changes:
            self.findings["core_changes"]["src"] = src_changes

        # Detectar cambios en src-core/
        src_core_changes = self._git_changes("src-core/")
        if src_core_changes:
            self.findings["core_changes"]["src-core"] = src_core_changes

        # Detectar cambios en src-db/ (solo sourcedata del core)
        src_db_changes = self._git_changes("src-db/")
        if src_db_changes:
            self.findings["core_changes"]["src-db"] = src_db_changes

        # Detectar cambios en módulos oficiales
        log.info("Analizando alteraciones en módulos oficiales (vía Git)...")
        for mod in official_modules:
            rel_path = os.path.relpath(mod["directory"], str(self.root))
            changes = self._git_changes(rel_path + "/")
            if changes:
                self.findings["official_changes"][mod["name"]] = changes

        # Resumen
        self._compute_summary()

    def _git_changes(self, path: str) -> dict | None:
        """Obtiene cambios Git para un path."""
        full_path = self.root / path
        if not full_path.exists():
            return None

        changes = {"modified": [], "added": [], "deleted": []}

        try:
            # git status para archivos tracked modificados y untracked
            result = subprocess.run(
                ["git", "status", "--porcelain", "--", path],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.root),
            )
            if result.returncode != 0:
                return None

            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                status = line[:2]
                filepath = line[3:].strip()
                # Quitar comillas si las hay
                if filepath.startswith('"') and filepath.endswith('"'):
                    filepath = filepath[1:-1]

                if status.strip() in ("M", "MM", "AM"):
                    changes["modified"].append(filepath)
                elif status.strip() in ("??", "A"):
                    changes["added"].append(filepath)
                elif status.strip() == "D":
                    changes["deleted"].append(filepath)

            # git diff para obtener stats de archivos tracked modificados
            result2 = subprocess.run(
                ["git", "diff", "--stat", "--", path],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.root),
            )
            if result2.stdout.strip():
                changes["diff_stat"] = result2.stdout.strip()

            # También incluir staged changes
            result3 = subprocess.run(
                ["git", "diff", "--cached", "--stat", "--", path],
                capture_output=True, text=True, timeout=30,
                cwd=str(self.root),
            )
            if result3.stdout.strip():
                changes["staged_diff_stat"] = result3.stdout.strip()

        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            log.warning(f"Error ejecutando git para {path}: {e}")
            return None

        if not changes["modified"] and not changes["added"] and not changes["deleted"]:
            return None

        return changes

    def _detect_with_manifest(self, official_modules: list):
        """Usa un archivo de checksums para detectar cambios."""
        self.findings["method"] = "manifest"

        try:
            with open(self.manifest_path) as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.error(f"No se pudo cargar el manifiesto: {e}")
            self.findings["method"] = "manifest_error"
            return

        log.info("Comparando archivos contra manifiesto de checksums...")

        # Comparar archivos
        for rel_path, expected_hash in manifest.items():
            full_path = self.root / rel_path
            if not full_path.exists():
                # Determinar si es core u oficial
                target = self._categorize_path(rel_path, official_modules)
                if target:
                    target.setdefault("deleted", []).append(rel_path)
                continue

            actual_hash = _file_sha256(str(full_path))
            if actual_hash != expected_hash:
                target = self._categorize_path(rel_path, official_modules)
                if target:
                    target.setdefault("modified", []).append(rel_path)

        # Buscar archivos añadidos (no en el manifiesto)
        for scan_dir in ["modules_core", "src", "src-core", "src-db"]:
            scan_path = self.root / scan_dir
            if not scan_path.is_dir():
                continue
            for fpath in scan_path.rglob("*"):
                if fpath.is_file():
                    rel = str(fpath.relative_to(self.root))
                    if rel not in manifest:
                        target = self._categorize_path(rel, official_modules)
                        if target:
                            target.setdefault("added", []).append(rel)

        self._compute_summary()

    def _categorize_path(self, rel_path: str, official_modules: list) -> dict | None:
        """Categoriza un path como core u oficial."""
        if rel_path.startswith("modules_core/") or rel_path.startswith("src/") \
                or rel_path.startswith("src-core/") or rel_path.startswith("src-db/"):
            return self.findings.setdefault("core_changes", {})

        for mod in official_modules:
            mod_rel = os.path.relpath(mod["directory"], str(self.root))
            if rel_path.startswith(mod_rel + "/"):
                return self.findings["official_changes"].setdefault(mod["name"], {})

        return None

    def _compute_summary(self):
        """Calcula el resumen de alteraciones."""
        total_mod = 0
        total_add = 0
        total_del = 0

        for changes in self.findings["core_changes"].values():
            if isinstance(changes, dict):
                total_mod += len(changes.get("modified", []))
                total_add += len(changes.get("added", []))
                total_del += len(changes.get("deleted", []))

        for mod_changes in self.findings["official_changes"].values():
            if isinstance(mod_changes, dict):
                total_mod += len(mod_changes.get("modified", []))
                total_add += len(mod_changes.get("added", []))
                total_del += len(mod_changes.get("deleted", []))

        self.findings["summary"] = {
            "total_modified": total_mod,
            "total_added": total_add,
            "total_deleted": total_del,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 4. CustomizationAnalyzer – Análisis de customizaciones
# ═══════════════════════════════════════════════════════════════════════════

class CustomizationAnalyzer:
    """Analiza el alcance de las customizaciones."""

    def __init__(self, root: Path, db_conn=None):
        self.root = root
        self.db_conn = db_conn
        self.results = {}

    def analyze(self, custom_modules: list):
        """Analiza cada módulo custom."""
        if self.db_conn:
            self._analyze_from_db(custom_modules)
        else:
            self._analyze_from_filesystem(custom_modules)

    def _analyze_from_db(self, custom_modules: list):
        """Analiza customizaciones usando consultas a la base de datos."""
        module_ids = [m["ad_module_id"] for m in custom_modules if m["ad_module_id"]]
        if not module_ids:
            log.warning("No hay módulos custom con ID para consultar en BD")
            self._analyze_from_filesystem(custom_modules)
            return

        log.info(f"Consultando base de datos para {len(module_ids)} módulos custom...")
        cur = self.db_conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        try:
            # Consulta agregada para todos los módulos
            cur.execute("""
                SELECT
                    m.ad_module_id,
                    m.name,
                    m.javapackage,
                    m.version,
                    (SELECT COUNT(*) FROM ad_table t WHERE t.ad_module_id = m.ad_module_id) AS table_count,
                    (SELECT COUNT(*) FROM ad_column c WHERE c.ad_module_id = m.ad_module_id) AS column_count,
                    (SELECT COUNT(*) FROM ad_window w WHERE w.ad_module_id = m.ad_module_id) AS window_count,
                    (SELECT COUNT(*) FROM ad_tab tb WHERE tb.ad_module_id = m.ad_module_id) AS tab_count,
                    (SELECT COUNT(*) FROM ad_process p WHERE p.ad_module_id = m.ad_module_id) AS process_count,
                    (SELECT COUNT(*) FROM ad_field f WHERE f.ad_module_id = m.ad_module_id) AS field_count,
                    (SELECT COUNT(*) FROM ad_reference r WHERE r.ad_module_id = m.ad_module_id) AS reference_count,
                    (SELECT COUNT(*) FROM ad_callout ca WHERE ca.ad_module_id = m.ad_module_id) AS callout_count
                FROM ad_module m
                WHERE m.ad_module_id = ANY(%s)
                ORDER BY m.name
            """, (module_ids,))

            db_results = {row["ad_module_id"]: dict(row) for row in cur.fetchall()}
        except Exception as e:
            log.warning(f"Error en consulta a BD: {e}")
            self._analyze_from_filesystem(custom_modules)
            return
        finally:
            cur.close()

        # Combinar resultados de BD con info de filesystem
        for mod in custom_modules:
            mod_id = mod["ad_module_id"]
            db_info = db_results.get(mod_id, {})

            # Contar reportes JRXML
            jrxml_count = _count_files_by_ext(Path(mod["directory"]), ".jrxml")

            self.results[mod["name"]] = {
                "ad_module_id": mod_id,
                "java_package": mod["java_package"],
                "version": mod["version"],
                "author": mod["author"],
                "is_in_development": mod["is_in_development"],
                "source_files": mod["source_file_count"],
                "lines_of_code": mod["loc"],
                "tables": db_info.get("table_count", 0),
                "columns": db_info.get("column_count", 0),
                "windows": db_info.get("window_count", 0),
                "tabs": db_info.get("tab_count", 0),
                "processes": db_info.get("process_count", 0),
                "fields": db_info.get("field_count", 0),
                "references": db_info.get("reference_count", 0),
                "callouts": db_info.get("callout_count", 0),
                "reports_jrxml": jrxml_count,
            }

    def _analyze_from_filesystem(self, custom_modules: list):
        """Analiza customizaciones parseando archivos XML (sin BD)."""
        log.info("Analizando customizaciones desde sistema de archivos (sin BD)...")

        for mod in custom_modules:
            sourcedata_dir = Path(mod["directory"]) / "src-db" / "database" / "sourcedata"
            mod_id = mod["ad_module_id"]

            counts = {
                "tables": 0, "columns": 0, "windows": 0,
                "tabs": 0, "processes": 0, "fields": 0,
                "references": 0, "callouts": 0,
            }

            if sourcedata_dir.is_dir() and mod_id:
                xml_count_map = {
                    "AD_TABLE.xml": ("AD_TABLE", "tables"),
                    "AD_COLUMN.xml": ("AD_COLUMN", "columns"),
                    "AD_WINDOW.xml": ("AD_WINDOW", "windows"),
                    "AD_TAB.xml": ("AD_TAB", "tabs"),
                    "AD_PROCESS.xml": ("AD_PROCESS", "processes"),
                    "AD_FIELD.xml": ("AD_FIELD", "fields"),
                    "AD_REFERENCE.xml": ("AD_REFERENCE", "references"),
                    "AD_CALLOUT.xml": ("AD_CALLOUT", "callouts"),
                }
                for filename, (tag, key) in xml_count_map.items():
                    xml_path = sourcedata_dir / filename
                    if xml_path.exists():
                        counts[key] = _count_xml_records(str(xml_path), tag, mod_id)

            jrxml_count = _count_files_by_ext(Path(mod["directory"]), ".jrxml")

            self.results[mod["name"]] = {
                "ad_module_id": mod_id,
                "java_package": mod["java_package"],
                "version": mod["version"],
                "author": mod["author"],
                "is_in_development": mod["is_in_development"],
                "source_files": mod["source_file_count"],
                "lines_of_code": mod["loc"],
                "reports_jrxml": jrxml_count,
                **counts,
            }

    def get_totals(self) -> dict:
        """Retorna totales agregados."""
        totals = defaultdict(int)
        numeric_keys = [
            "source_files", "lines_of_code", "tables", "columns", "windows",
            "tabs", "processes", "fields", "references", "callouts", "reports_jrxml",
        ]
        for mod_data in self.results.values():
            for key in numeric_keys:
                totals[key] += mod_data.get(key, 0)
        return dict(totals)


# ═══════════════════════════════════════════════════════════════════════════
# 5. FunctionalMapper – Mapeo de impacto funcional
# ═══════════════════════════════════════════════════════════════════════════

class FunctionalMapper:
    """Mapea módulos custom a áreas funcionales del ERP."""

    def __init__(self, root: Path, areas_config: dict | None = None, db_conn=None):
        self.root = root
        self.db_conn = db_conn
        self.areas = areas_config or EMBEDDED_FUNCTIONAL_AREAS
        self.mapping = defaultdict(list)  # area -> [module_names]

    def map_modules(self, custom_modules: list, customization_results: dict):
        """Mapea cada módulo custom a áreas funcionales."""
        for mod in custom_modules:
            name = mod["name"]
            pkg = mod.get("java_package", "")
            matched_areas = set()

            # 1. Matching por paquete Java
            for area, config in self.areas.items():
                for area_pkg in config.get("packages", []):
                    if pkg.startswith(area_pkg) or area_pkg.startswith(pkg):
                        matched_areas.add(area)

            # 2. Matching por tablas (desde BD o XML)
            module_tables = self._get_module_tables(mod)
            for area, config in self.areas.items():
                area_tables = set(t.upper() for t in config.get("tables", []))
                for table in module_tables:
                    if table.upper() in area_tables:
                        matched_areas.add(area)

            # 3. Matching por ventanas (desde BD o XML)
            module_windows = self._get_module_windows(mod)
            for area, config in self.areas.items():
                for pattern in config.get("windows", []):
                    regex = pattern.replace("%", ".*")
                    for window in module_windows:
                        if re.search(regex, window, re.IGNORECASE):
                            matched_areas.add(area)

            if not matched_areas:
                matched_areas.add("other")

            for area in matched_areas:
                self.mapping[area].append(name)

    def _get_module_tables(self, mod: dict) -> list:
        """Obtiene las tablas creadas/modificadas por un módulo."""
        tables = []
        mod_id = mod.get("ad_module_id")

        if self.db_conn and mod_id:
            try:
                cur = self.db_conn.cursor()
                cur.execute(
                    "SELECT tablename FROM ad_table WHERE ad_module_id = %s",
                    (mod_id,)
                )
                tables = [row[0] for row in cur.fetchall()]
                cur.close()
                return tables
            except Exception:
                pass

        # Fallback: parsear AD_TABLE.xml
        xml_path = Path(mod["directory"]) / "src-db" / "database" / "sourcedata" / "AD_TABLE.xml"
        if xml_path.exists():
            try:
                tree = ET.parse(str(xml_path))
                for elem in tree.getroot():
                    name = _xml_text(elem, "TABLENAME") or _xml_text(elem, "NAME")
                    if name:
                        tables.append(name)
            except ET.ParseError:
                pass

        return tables

    def _get_module_windows(self, mod: dict) -> list:
        """Obtiene las ventanas de un módulo."""
        windows = []
        mod_id = mod.get("ad_module_id")

        if self.db_conn and mod_id:
            try:
                cur = self.db_conn.cursor()
                cur.execute(
                    "SELECT name FROM ad_window WHERE ad_module_id = %s",
                    (mod_id,)
                )
                windows = [row[0] for row in cur.fetchall()]
                cur.close()
                return windows
            except Exception:
                pass

        # Fallback: parsear AD_WINDOW.xml
        xml_path = Path(mod["directory"]) / "src-db" / "database" / "sourcedata" / "AD_WINDOW.xml"
        if xml_path.exists():
            try:
                tree = ET.parse(str(xml_path))
                for elem in tree.getroot():
                    name = _xml_text(elem, "NAME")
                    if name:
                        windows.append(name)
            except ET.ParseError:
                pass

        return windows

    def get_impact_summary(self) -> dict:
        """Retorna un resumen del impacto por área."""
        summary = {}
        for area, config in self.areas.items():
            modules_in_area = self.mapping.get(area, [])
            summary[area] = {
                "description": config.get("description", ""),
                "affected_modules": modules_in_area,
                "module_count": len(modules_in_area),
                "impact_level": "alto" if len(modules_in_area) > 3
                    else "medio" if len(modules_in_area) > 1
                    else "bajo" if len(modules_in_area) == 1
                    else "ninguno",
            }

        # Añadir "other" si existe
        if "other" in self.mapping:
            summary["other"] = {
                "description": "Módulos no clasificados en un área específica",
                "affected_modules": self.mapping["other"],
                "module_count": len(self.mapping["other"]),
                "impact_level": "bajo",
            }

        return summary


# ═══════════════════════════════════════════════════════════════════════════
# 6. EffortEstimator – Estimación de esfuerzo
# ═══════════════════════════════════════════════════════════════════════════

class EffortEstimator:
    """Estima el esfuerzo de migración basándose en métricas cuantificables."""

    def __init__(self, current_version: str, target_version: str | None = None):
        self.current_version = current_version
        self.target_version = target_version
        self.breakdown = {}
        self.total_points = 0

    def estimate(self, customization_totals: dict, tampering_summary: dict,
                 custom_modules_detail: dict):
        """Calcula la estimación de esfuerzo."""
        pts = {}

        # Archivos Java custom
        java_files = customization_totals.get("source_files", 0)
        pts["custom_java_files"] = {
            "count": java_files,
            "points": java_files * EFFORT_WEIGHTS["custom_java_file"],
            "description": "Archivos fuente custom",
        }

        # LOC custom
        loc = customization_totals.get("lines_of_code", 0)
        pts["custom_loc"] = {
            "count": loc,
            "points": (loc // 100) * EFFORT_WEIGHTS["custom_loc_per_100"],
            "description": "Líneas de código custom (por cada 100)",
        }

        # Tablas custom
        tables = customization_totals.get("tables", 0)
        pts["custom_tables"] = {
            "count": tables,
            "points": tables * EFFORT_WEIGHTS["custom_table"],
            "description": "Tablas custom",
        }

        # Columnas custom (potencialmente en tablas existentes)
        columns = customization_totals.get("columns", 0)
        pts["custom_columns"] = {
            "count": columns,
            "points": columns * EFFORT_WEIGHTS["custom_column_on_existing"],
            "description": "Columnas custom",
        }

        # Ventanas custom
        windows = customization_totals.get("windows", 0)
        pts["custom_windows"] = {
            "count": windows,
            "points": windows * EFFORT_WEIGHTS["custom_window"],
            "description": "Ventanas custom",
        }

        # Tabs custom
        tabs = customization_totals.get("tabs", 0)
        pts["custom_tabs"] = {
            "count": tabs,
            "points": int(tabs * EFFORT_WEIGHTS["custom_tab"]),
            "description": "Pestañas custom",
        }

        # Procesos custom
        processes = customization_totals.get("processes", 0)
        pts["custom_processes"] = {
            "count": processes,
            "points": processes * EFFORT_WEIGHTS["custom_process"],
            "description": "Procesos custom",
        }

        # Reportes JRXML
        reports = customization_totals.get("reports_jrxml", 0)
        pts["custom_reports"] = {
            "count": reports,
            "points": reports * EFFORT_WEIGHTS["custom_report"],
            "description": "Reportes JRXML custom",
        }

        # Fields custom
        fields = customization_totals.get("fields", 0)
        pts["custom_fields"] = {
            "count": fields,
            "points": int(fields * EFFORT_WEIGHTS["custom_field"]),
            "description": "Campos custom",
        }

        # Archivos modificados en core
        modified = tampering_summary.get("total_modified", 0)
        pts["modified_core_files"] = {
            "count": modified,
            "points": modified * EFFORT_WEIGHTS["modified_core_file"],
            "description": "Archivos del core/oficiales modificados",
        }

        # Archivos eliminados en core
        deleted = tampering_summary.get("total_deleted", 0)
        pts["deleted_core_files"] = {
            "count": deleted,
            "points": deleted * EFFORT_WEIGHTS["deleted_core_file"],
            "description": "Archivos del core/oficiales eliminados",
        }

        # Archivos añadidos en core
        added = tampering_summary.get("total_added", 0)
        pts["added_core_files"] = {
            "count": added,
            "points": added * EFFORT_WEIGHTS["added_file_in_core"],
            "description": "Archivos añadidos en directorios core/oficiales",
        }

        # Distancia de versión
        version_gap = self._compute_version_distance()
        pts["version_distance"] = {
            "count": version_gap,
            "points": version_gap * EFFORT_WEIGHTS["version_distance_major"],
            "description": f"Distancia de versión (releases mayores) "
                          f"{self.current_version} → {self.target_version or 'última'}",
        }

        self.breakdown = pts
        self.total_points = sum(v["points"] for v in pts.values())

    def _compute_version_distance(self) -> int:
        """Calcula la distancia en releases mayores entre versiones."""
        if not self.target_version or self.current_version == "desconocida":
            return 0

        try:
            cur = _parse_etendo_version(self.current_version)
            tgt = _parse_etendo_version(self.target_version)
            if cur and tgt:
                # Cada combinación año.trimestre es un release mayor
                cur_major = cur[0] * 4 + cur[1]
                tgt_major = tgt[0] * 4 + tgt[1]
                return max(0, tgt_major - cur_major)
        except (ValueError, TypeError):
            pass
        return 0

    def get_effort_band(self) -> tuple:
        """Retorna la banda de esfuerzo."""
        for threshold, band, description in EFFORT_BANDS:
            if self.total_points <= threshold:
                return band, description
        return EFFORT_BANDS[-1][1], EFFORT_BANDS[-1][2]

    def get_result(self) -> dict:
        band, band_desc = self.get_effort_band()
        return {
            "total_points": self.total_points,
            "effort_band": band,
            "effort_description": band_desc,
            "breakdown": self.breakdown,
            "top_risk_items": self._get_top_risks(),
        }

    def _get_top_risks(self) -> list:
        """Retorna los factores de mayor riesgo ordenados por puntos."""
        items = [
            {"factor": v["description"], "count": v["count"], "points": v["points"]}
            for k, v in self.breakdown.items()
            if v["points"] > 0
        ]
        items.sort(key=lambda x: x["points"], reverse=True)
        return items[:10]


# ═══════════════════════════════════════════════════════════════════════════
# 7. ReportGenerator – Generación de informes
# ═══════════════════════════════════════════════════════════════════════════

class ReportGenerator:
    """Genera informes en JSON y HTML."""

    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, report_data: dict, formats: list):
        """Genera los informes en los formatos solicitados."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        generated = []

        if "json" in formats or "all" in formats:
            path = self.output_dir / f"etendo_diagnosis_{timestamp}.json"
            self._write_json(report_data, path)
            generated.append(str(path))

        if "html" in formats or "all" in formats:
            path = self.output_dir / f"etendo_diagnosis_{timestamp}.html"
            self._write_html(report_data, path)
            generated.append(str(path))

        if "text" in formats or "all" in formats:
            path = self.output_dir / f"etendo_diagnosis_{timestamp}.txt"
            self._write_text(report_data, path)
            generated.append(str(path))

        return generated

    def _write_json(self, data: dict, path: Path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        log.info(f"Informe JSON: {path}")

    def _write_html(self, data: dict, path: Path):
        html = self._render_html(data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log.info(f"Informe HTML: {path}")

    def _write_text(self, data: dict, path: Path):
        text = self._render_text(data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        log.info(f"Informe texto: {path}")

    def _render_html(self, data: dict) -> str:
        """Genera un informe HTML completo."""
        install = data.get("installation", {})
        modules = data.get("modules", {})
        tampering = data.get("tampering", {})
        customization = data.get("customization", {})
        functional = data.get("functional_impact", {})
        effort = data.get("effort_estimation", {})

        # Colores para bandas de esfuerzo
        band_colors = {
            "Bajo": "#27ae60", "Medio": "#f39c12",
            "Alto": "#e74c3c", "Muy Alto": "#8e44ad",
        }
        band = effort.get("effort_band", "")
        band_color = band_colors.get(band, "#333")

        # Construir filas de módulos custom
        custom_rows = ""
        for name, info in customization.get("details", {}).items():
            custom_rows += f"""
            <tr>
                <td>{_h(name)}</td>
                <td>{_h(info.get('java_package', ''))}</td>
                <td>{_h(info.get('version', ''))}</td>
                <td class="num">{info.get('tables', 0)}</td>
                <td class="num">{info.get('columns', 0)}</td>
                <td class="num">{info.get('windows', 0)}</td>
                <td class="num">{info.get('processes', 0)}</td>
                <td class="num">{info.get('reports_jrxml', 0)}</td>
                <td class="num">{info.get('source_files', 0)}</td>
                <td class="num">{info.get('lines_of_code', 0):,}</td>
            </tr>"""

        # Filas de impacto funcional
        functional_rows = ""
        for area, info in functional.items():
            if info.get("module_count", 0) == 0:
                continue
            impact = info.get("impact_level", "ninguno")
            impact_class = {"alto": "high", "medio": "medium", "bajo": "low"}.get(impact, "")
            functional_rows += f"""
            <tr>
                <td>{_h(area.replace('_', ' ').title())}</td>
                <td>{_h(info.get('description', ''))}</td>
                <td class="{impact_class}">{impact.upper()}</td>
                <td class="num">{info.get('module_count', 0)}</td>
                <td>{', '.join(info.get('affected_modules', []))}</td>
            </tr>"""

        # Filas de alteraciones
        tampering_detail = ""
        tamp_summary = tampering.get("summary", {})
        if tamp_summary.get("total_modified", 0) + tamp_summary.get("total_added", 0) + tamp_summary.get("total_deleted", 0) > 0:
            for section, label in [("core_changes", "Core"), ("official_changes", "Módulos oficiales")]:
                for key, changes in tampering.get(section, {}).items():
                    if isinstance(changes, dict):
                        for change_type in ["modified", "added", "deleted"]:
                            for f in changes.get(change_type, []):
                                tampering_detail += f"""
                <tr>
                    <td>{_h(label)}</td>
                    <td>{_h(key)}</td>
                    <td>{change_type}</td>
                    <td>{_h(f)}</td>
                </tr>"""

        # Filas de top risks
        risk_rows = ""
        for item in effort.get("top_risk_items", []):
            risk_rows += f"""
            <tr>
                <td>{_h(item.get('factor', ''))}</td>
                <td class="num">{item.get('count', 0)}</td>
                <td class="num">{item.get('points', 0)}</td>
            </tr>"""

        # Módulos inventario completo
        all_modules_rows = ""
        for mod in modules.get("all", []):
            cls = mod.get("classification", "")
            cls_class = {"core": "core", "official_extension": "official", "custom": "custom"}.get(cls, "")
            all_modules_rows += f"""
            <tr class="{cls_class}">
                <td>{_h(mod.get('name', ''))}</td>
                <td>{_h(mod.get('java_package', ''))}</td>
                <td>{_h(mod.get('version', ''))}</td>
                <td>{_h(cls)}</td>
                <td>{_h(mod.get('author', ''))}</td>
                <td>{_h(mod.get('license_type', ''))}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Diagnóstico Etendo - {_h(install.get('version', ''))}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; }}
    h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; margin-bottom: 20px; }}
    h2 {{ color: #2c3e50; margin-top: 30px; margin-bottom: 15px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
    h3 {{ color: #34495e; margin-top: 20px; margin-bottom: 10px; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                     gap: 15px; margin: 20px 0; }}
    .card {{ background: #f8f9fa; border-radius: 8px; padding: 20px; border-left: 4px solid #3498db; }}
    .card.warning {{ border-left-color: #e74c3c; }}
    .card.success {{ border-left-color: #27ae60; }}
    .card h3 {{ margin: 0 0 5px; font-size: 14px; color: #666; text-transform: uppercase; }}
    .card .value {{ font-size: 28px; font-weight: bold; color: #2c3e50; }}
    .card .detail {{ font-size: 12px; color: #888; margin-top: 5px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px; }}
    th {{ background: #2c3e50; color: white; padding: 10px 12px; text-align: left; }}
    td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
    tr:hover {{ background: #f5f5f5; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .high {{ color: #e74c3c; font-weight: bold; }}
    .medium {{ color: #f39c12; font-weight: bold; }}
    .low {{ color: #27ae60; }}
    .core {{ background: #eaf2f8; }}
    .official {{ background: #eafaf1; }}
    .custom {{ background: #fef9e7; }}
    .effort-badge {{ display: inline-block; padding: 8px 20px; border-radius: 20px;
                     color: white; font-weight: bold; font-size: 18px;
                     background: {band_color}; }}
    .timestamp {{ color: #999; font-size: 12px; margin-top: 30px; text-align: center; }}
    .alert {{ background: #fdecea; border: 1px solid #e74c3c; border-radius: 8px;
              padding: 15px; margin: 15px 0; }}
    .alert strong {{ color: #e74c3c; }}
    @media print {{ body {{ font-size: 12px; }} .card .value {{ font-size: 22px; }} }}
</style>
</head>
<body>

<h1>Diagnóstico de Instalación Etendo</h1>

<!-- Resumen ejecutivo -->
<div class="summary-grid">
    <div class="card">
        <h3>Versión instalada</h3>
        <div class="value">{_h(install.get('version', 'N/A'))}</div>
        <div class="detail">{_h(install.get('version_label', '') or '')}</div>
    </div>
    <div class="card">
        <h3>Módulos totales</h3>
        <div class="value">{modules.get('total', 0)}</div>
        <div class="detail">
            Core: {modules.get('core_count', 0)} |
            Oficiales: {modules.get('official_count', 0)} |
            Custom: {modules.get('custom_count', 0)}
        </div>
    </div>
    <div class="card {'warning' if tamp_summary.get('total_modified', 0) > 0 else 'success'}">
        <h3>Alteraciones detectadas</h3>
        <div class="value">{tamp_summary.get('total_modified', 0) + tamp_summary.get('total_added', 0) + tamp_summary.get('total_deleted', 0)}</div>
        <div class="detail">
            Modificados: {tamp_summary.get('total_modified', 0)} |
            Añadidos: {tamp_summary.get('total_added', 0)} |
            Eliminados: {tamp_summary.get('total_deleted', 0)}
        </div>
    </div>
    <div class="card">
        <h3>Esfuerzo estimado</h3>
        <div class="value"><span class="effort-badge">{_h(effort.get('effort_band', 'N/A'))}</span></div>
        <div class="detail">{_h(effort.get('effort_description', ''))} ({effort.get('total_points', 0)} pts)</div>
    </div>
</div>

<!-- Información de la instalación -->
<h2>1. Información de la instalación</h2>
<table>
    <tr><td><strong>Ruta</strong></td><td>{_h(install.get('root_path', ''))}</td></tr>
    <tr><td><strong>Versión</strong></td><td>{_h(install.get('version', ''))}</td></tr>
    <tr><td><strong>Etiqueta</strong></td><td>{_h(install.get('version_label', '') or 'N/A')}</td></tr>
    <tr><td><strong>Git disponible</strong></td><td>{'Sí' if install.get('has_git') else 'No'}</td></tr>
    <tr><td><strong>Rama Git</strong></td><td>{_h(install.get('git_branch', '') or 'N/A')}</td></tr>
    <tr><td><strong>BD conectada</strong></td><td>{'Sí' if install.get('db_configured') else 'No'}</td></tr>
</table>

<!-- Detección de alteraciones -->
<h2>2. Detección de alteraciones en código core y oficial</h2>
<p>Método de detección: <strong>{_h(tampering.get('method', 'no disponible'))}</strong></p>
{f'''
<div class="alert">
    <strong>⚠ Se detectaron alteraciones en código core u oficial.</strong>
    Esto puede complicar significativamente la migración.
</div>
''' if tamp_summary.get('total_modified', 0) + tamp_summary.get('total_added', 0) + tamp_summary.get('total_deleted', 0) > 0 else '<p>No se detectaron alteraciones.</p>'}

{f'''
<table>
    <thead><tr><th>Sección</th><th>Módulo/Área</th><th>Tipo</th><th>Archivo</th></tr></thead>
    <tbody>{tampering_detail}</tbody>
</table>
''' if tampering_detail else ''}

<!-- Inventario de módulos customizados -->
<h2>3. Análisis de customizaciones</h2>
<div class="summary-grid">
    <div class="card">
        <h3>Módulos custom</h3>
        <div class="value">{modules.get('custom_count', 0)}</div>
    </div>
    <div class="card">
        <h3>Tablas custom</h3>
        <div class="value">{customization.get('totals', {}).get('tables', 0)}</div>
    </div>
    <div class="card">
        <h3>Columnas custom</h3>
        <div class="value">{customization.get('totals', {}).get('columns', 0)}</div>
    </div>
    <div class="card">
        <h3>Líneas de código</h3>
        <div class="value">{customization.get('totals', {}).get('lines_of_code', 0):,}</div>
    </div>
</div>

{f'''
<table>
    <thead>
        <tr>
            <th>Módulo</th><th>Paquete Java</th><th>Versión</th>
            <th>Tablas</th><th>Columnas</th><th>Ventanas</th>
            <th>Procesos</th><th>Reportes</th><th>Archivos src</th><th>LOC</th>
        </tr>
    </thead>
    <tbody>{custom_rows}</tbody>
</table>
''' if custom_rows else '<p>No se encontraron módulos custom.</p>'}

<!-- Impacto funcional -->
<h2>4. Impacto funcional por áreas</h2>
{f'''
<table>
    <thead>
        <tr><th>Área</th><th>Descripción</th><th>Impacto</th><th>Módulos</th><th>Detalle</th></tr>
    </thead>
    <tbody>{functional_rows}</tbody>
</table>
''' if functional_rows else '<p>Sin impacto funcional detectado.</p>'}

<!-- Estimación de esfuerzo -->
<h2>5. Estimación de esfuerzo de migración</h2>
<p>Puntuación total: <strong>{effort.get('total_points', 0)} puntos</strong> →
   <span class="effort-badge">{_h(effort.get('effort_band', ''))}</span>
   ({_h(effort.get('effort_description', ''))})</p>

<h3>Factores principales de esfuerzo</h3>
{f'''
<table>
    <thead><tr><th>Factor</th><th>Cantidad</th><th>Puntos</th></tr></thead>
    <tbody>{risk_rows}</tbody>
</table>
''' if risk_rows else ''}

<!-- Inventario completo de módulos -->
<h2>6. Inventario completo de módulos</h2>
<p>
    <span style="display:inline-block;width:12px;height:12px;background:#eaf2f8;border:1px solid #ccc;"></span> Core
    <span style="display:inline-block;width:12px;height:12px;background:#eafaf1;border:1px solid #ccc;margin-left:10px;"></span> Oficial
    <span style="display:inline-block;width:12px;height:12px;background:#fef9e7;border:1px solid #ccc;margin-left:10px;"></span> Custom
</p>
<table>
    <thead>
        <tr><th>Nombre</th><th>Paquete Java</th><th>Versión</th>
            <th>Clasificación</th><th>Autor</th><th>Licencia</th></tr>
    </thead>
    <tbody>{all_modules_rows}</tbody>
</table>

<div class="timestamp">
    Informe generado el {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} por etendo_diagnose.py
</div>

</body>
</html>"""
        return html

    def _render_text(self, data: dict) -> str:
        """Genera un informe en texto plano."""
        lines = []
        sep = "=" * 80

        install = data.get("installation", {})
        modules = data.get("modules", {})
        tampering = data.get("tampering", {})
        customization = data.get("customization", {})
        functional = data.get("functional_impact", {})
        effort = data.get("effort_estimation", {})
        tamp_summary = tampering.get("summary", {})

        lines.append(sep)
        lines.append("  DIAGNÓSTICO DE INSTALACIÓN ETENDO")
        lines.append(sep)
        lines.append("")

        # Resumen ejecutivo
        lines.append("RESUMEN EJECUTIVO")
        lines.append("-" * 40)
        lines.append(f"  Versión instalada:     {install.get('version', 'N/A')}")
        lines.append(f"  Módulos totales:       {modules.get('total', 0)}")
        lines.append(f"    - Core:              {modules.get('core_count', 0)}")
        lines.append(f"    - Oficiales:         {modules.get('official_count', 0)}")
        lines.append(f"    - Custom:            {modules.get('custom_count', 0)}")
        total_tamp = tamp_summary.get('total_modified', 0) + tamp_summary.get('total_added', 0) + tamp_summary.get('total_deleted', 0)
        lines.append(f"  Alteraciones:          {total_tamp}")
        lines.append(f"  Esfuerzo estimado:     {effort.get('effort_band', 'N/A')} "
                     f"({effort.get('total_points', 0)} pts) - {effort.get('effort_description', '')}")
        lines.append("")

        # Alteraciones
        lines.append(sep)
        lines.append("  ALTERACIONES EN CÓDIGO CORE/OFICIAL")
        lines.append(sep)
        lines.append(f"  Método: {tampering.get('method', 'N/A')}")
        lines.append(f"  Modificados: {tamp_summary.get('total_modified', 0)}")
        lines.append(f"  Añadidos:    {tamp_summary.get('total_added', 0)}")
        lines.append(f"  Eliminados:  {tamp_summary.get('total_deleted', 0)}")

        for section, label in [("core_changes", "Core"), ("official_changes", "Oficiales")]:
            for key, changes in tampering.get(section, {}).items():
                if isinstance(changes, dict):
                    for change_type in ["modified", "added", "deleted"]:
                        for f in changes.get(change_type, []):
                            lines.append(f"  [{change_type:8s}] {label}/{key}: {f}")
        lines.append("")

        # Customizaciones
        lines.append(sep)
        lines.append("  ANÁLISIS DE CUSTOMIZACIONES")
        lines.append(sep)
        totals = customization.get("totals", {})
        lines.append(f"  Tablas:          {totals.get('tables', 0)}")
        lines.append(f"  Columnas:        {totals.get('columns', 0)}")
        lines.append(f"  Ventanas:        {totals.get('windows', 0)}")
        lines.append(f"  Procesos:        {totals.get('processes', 0)}")
        lines.append(f"  Reportes JRXML:  {totals.get('reports_jrxml', 0)}")
        lines.append(f"  Archivos fuente: {totals.get('source_files', 0)}")
        lines.append(f"  Líneas código:   {totals.get('lines_of_code', 0):,}")
        lines.append("")

        for name, info in customization.get("details", {}).items():
            lines.append(f"  [{name}]")
            lines.append(f"    Paquete: {info.get('java_package', '')}")
            lines.append(f"    Tablas: {info.get('tables', 0)} | Columnas: {info.get('columns', 0)} "
                         f"| Ventanas: {info.get('windows', 0)} | Procesos: {info.get('processes', 0)}")
            lines.append(f"    Fuentes: {info.get('source_files', 0)} archivos, "
                         f"{info.get('lines_of_code', 0):,} LOC")
        lines.append("")

        # Impacto funcional
        lines.append(sep)
        lines.append("  IMPACTO FUNCIONAL POR ÁREAS")
        lines.append(sep)
        for area, info in functional.items():
            if info.get("module_count", 0) > 0:
                lines.append(f"  {area.replace('_', ' ').title():20s} "
                             f"Impacto: {info.get('impact_level', '').upper():8s} "
                             f"Módulos: {', '.join(info.get('affected_modules', []))}")
        lines.append("")

        # Estimación de esfuerzo
        lines.append(sep)
        lines.append("  ESTIMACIÓN DE ESFUERZO")
        lines.append(sep)
        lines.append(f"  Total: {effort.get('total_points', 0)} puntos → "
                     f"{effort.get('effort_band', '')} ({effort.get('effort_description', '')})")
        lines.append("")
        lines.append("  Desglose:")
        for item in effort.get("top_risk_items", []):
            lines.append(f"    {item.get('factor', ''):45s} x{item.get('count', 0):5d} = "
                         f"{item.get('points', 0):6d} pts")
        lines.append("")

        lines.append(sep)
        lines.append(f"  Generado: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(sep)

        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# Funciones auxiliares
# ═══════════════════════════════════════════════════════════════════════════

def _xml_text(element, tag: str) -> str | None:
    """Extrae texto de un subelemento XML."""
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_properties(filepath: str) -> dict:
    """Parsea un archivo .properties de Java."""
    props = {}
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("!"):
                    if "=" in line:
                        key, value = line.split("=", 1)
                        props[key.strip()] = value.strip()
    except OSError:
        pass
    return props


def _count_source(directory: Path) -> tuple:
    """Cuenta archivos fuente y líneas de código en un directorio."""
    file_count = 0
    loc = 0
    try:
        for fpath in directory.rglob("*"):
            if fpath.is_file() and fpath.suffix in CODE_EXTENSIONS:
                file_count += 1
                try:
                    with open(fpath, encoding="utf-8", errors="replace") as f:
                        loc += sum(1 for line in f if line.strip())
                except OSError:
                    pass
    except OSError:
        pass
    return file_count, loc


def _count_files_by_ext(directory: Path, ext: str) -> int:
    """Cuenta archivos con una extensión específica."""
    count = 0
    try:
        for fpath in directory.rglob(f"*{ext}"):
            if fpath.is_file():
                count += 1
    except OSError:
        pass
    return count


def _count_xml_records(xml_path: str, tag: str, module_id: str) -> int:
    """Cuenta registros XML que pertenecen a un módulo específico."""
    count = 0
    try:
        tree = ET.parse(xml_path)
        for elem in tree.getroot():
            if elem.tag == tag:
                mid = _xml_text(elem, "AD_MODULE_ID")
                if mid == module_id:
                    count += 1
    except (ET.ParseError, OSError):
        pass
    return count


def _file_sha256(filepath: str) -> str:
    """Calcula el SHA-256 de un archivo."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_etendo_version(version: str) -> tuple | None:
    """Parsea una versión de Etendo (YY.Q.PATCH) a tupla."""
    # Limpiar rangos de versión como [25.1.0,26.1.0)
    version = version.strip("[]() ")
    if "," in version:
        version = version.split(",")[0]

    m = re.match(r"(\d+)\.(\d+)\.?(\d+)?", version)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    return None


def _h(text) -> str:
    """Escapa HTML."""
    if text is None:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _load_functional_areas(script_dir: Path) -> dict:
    """Carga el mapeo de áreas funcionales."""
    json_path = script_dir / "functional_areas.json"
    if json_path.exists():
        try:
            with open(json_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    return EMBEDDED_FUNCTIONAL_AREAS


# ═══════════════════════════════════════════════════════════════════════════
# 8. Main – Punto de entrada
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Herramienta de diagnóstico para instalaciones de Etendo ERP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python3 etendo_diagnose.py
  python3 etendo_diagnose.py --target-version 25.4.0
  python3 etendo_diagnose.py --skip-db --format text
  python3 etendo_diagnose.py --manifest etendo_manifest_24.3.0.json
        """,
    )
    parser.add_argument(
        "--target-version",
        help="Versión objetivo de Etendo para estimar esfuerzo de migración",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directorio donde generar los informes (default: directorio actual)",
    )
    parser.add_argument(
        "--format",
        default="all",
        choices=["json", "html", "text", "all"],
        help="Formato de salida (default: all)",
    )
    parser.add_argument(
        "--manifest",
        help="Ruta a un archivo de checksums para detección sin Git",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Omitir consultas a base de datos (análisis solo de filesystem)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Mostrar información detallada de depuración",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          ETENDO DIAGNOSE - Herramienta de diagnóstico      ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # ── 1. Descubrimiento de la instalación ──
    log.info("Paso 1/6: Detectando instalación de Etendo...")
    installation = EtendoInstallation(os.getcwd())

    if not installation.validate():
        sys.exit(1)

    installation.detect_version()
    installation.detect_db_config()
    installation.detect_git()

    log.info(f"  Versión: {installation.version}")
    log.info(f"  Git: {'Sí' if installation.has_git else 'No'} "
             f"{'(' + installation.git_branch + ')' if installation.git_branch else ''}")

    # ── Conexión a BD (opcional) ──
    db_conn = None
    if not args.skip_db and installation.db_config.get("database"):
        if DB_AVAILABLE:
            try:
                db_conn = psycopg2.connect(
                    host=installation.db_config["host"],
                    port=installation.db_config["port"],
                    dbname=installation.db_config["database"],
                    user=installation.db_config["user"],
                    password=installation.db_config["password"],
                )
                log.info(f"  Conectado a BD: {installation.db_config['database']}")
            except Exception as e:
                log.warning(f"  No se pudo conectar a BD: {e}")
                log.warning("  Continuando sin base de datos...")
        else:
            log.warning("  psycopg2 no disponible. Instalar con: pip install psycopg2-binary")
            log.warning("  Continuando sin base de datos...")

    # ── 2. Escaneo de módulos ──
    log.info("Paso 2/6: Escaneando módulos...")
    scanner = ModuleScanner(installation.root)
    scanner.scan()

    custom_modules = scanner.get_by_classification("custom")
    official_modules = scanner.get_by_classification("official_extension")

    # ── 3. Detección de alteraciones ──
    log.info("Paso 3/6: Detectando alteraciones en código core y oficial...")
    tampering = TamperingDetector(installation.root, installation.has_git, args.manifest)
    tampering.detect(official_modules)

    tamp_total = (tampering.findings["summary"]["total_modified"]
                  + tampering.findings["summary"]["total_added"]
                  + tampering.findings["summary"]["total_deleted"])
    if tamp_total > 0:
        log.warning(f"  ⚠ Se detectaron {tamp_total} alteraciones en código core/oficial")
    else:
        log.info("  Sin alteraciones detectadas")

    # ── 4. Análisis de customizaciones ──
    log.info("Paso 4/6: Analizando customizaciones...")
    customization = CustomizationAnalyzer(installation.root, db_conn)
    customization.analyze(custom_modules)

    totals = customization.get_totals()
    log.info(f"  Tablas: {totals.get('tables', 0)} | Columnas: {totals.get('columns', 0)} "
             f"| Ventanas: {totals.get('windows', 0)} | LOC: {totals.get('lines_of_code', 0):,}")

    # ── 5. Mapeo funcional ──
    log.info("Paso 5/6: Mapeando impacto funcional...")
    script_dir = Path(__file__).resolve().parent
    areas_config = _load_functional_areas(script_dir)
    mapper = FunctionalMapper(installation.root, areas_config, db_conn)
    mapper.map_modules(custom_modules, customization.results)

    # ── 6. Estimación de esfuerzo ──
    log.info("Paso 6/6: Estimando esfuerzo de migración...")
    estimator = EffortEstimator(installation.version, args.target_version)
    estimator.estimate(totals, tampering.findings["summary"], customization.results)

    band, band_desc = estimator.get_effort_band()
    log.info(f"  Esfuerzo: {band} ({estimator.total_points} pts) - {band_desc}")

    # ── Cerrar BD ──
    if db_conn:
        db_conn.close()

    # ── Generar informe ──
    report_data = {
        "generated_at": datetime.datetime.now().isoformat(),
        "tool_version": "1.0.0",
        "installation": installation.get_info(),
        "modules": {
            "total": len(scanner.modules),
            "core_count": len(scanner.get_by_classification("core")),
            "official_count": len(official_modules),
            "custom_count": len(custom_modules),
            "all": scanner.modules,
        },
        "tampering": tampering.findings,
        "customization": {
            "totals": totals,
            "details": customization.results,
        },
        "functional_impact": mapper.get_impact_summary(),
        "effort_estimation": estimator.get_result(),
    }

    reporter = ReportGenerator(args.output_dir)
    formats = [args.format] if args.format != "all" else ["json", "html", "text"]
    generated = reporter.generate(report_data, formats)

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  DIAGNÓSTICO COMPLETADO                                    ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Versión:      {installation.version:<44s}║")
    print(f"║  Módulos:      {len(scanner.modules)} total "
          f"({len(custom_modules)} custom)"
          f"{' ' * (36 - len(str(len(scanner.modules))) - len(str(len(custom_modules))))}║")
    print(f"║  Alteraciones: {tamp_total:<44d}║")
    print(f"║  Esfuerzo:     {band} ({estimator.total_points} pts)"
          f"{' ' * (44 - len(band) - len(str(estimator.total_points)) - 7)}║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  Informes generados:                                       ║")
    for g in generated:
        fname = os.path.basename(g)
        print(f"║    {fname:<56s}║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()


if __name__ == "__main__":
    main()
