# etendo-migration-agent

Herramienta de análisis de instalaciones Etendo/Openbravo on-premise para estimar el esfuerzo de migración a SaaS. Se ejecuta una vez en el servidor del cliente y genera un reporte JSON + HTML con el diagnóstico completo.

**Requiere únicamente Python 3.8+. Sin dependencias externas.**

---

## ¿Qué analiza?

- **Plataforma y versión**: detecta si la instalación es Etendo o Openbravo, y la versión de core instalada.
- **Módulos**: clasifica todos los módulos en 5 categorías según su origen y forma de gestión.
- **Divergencias en core**: compara los archivos fuente del cliente contra una base limpia (etendo-core-25.4.11.zip) para detectar diferencias, ya sean customizaciones o desactualización de versión.
- **Score de migración**: calcula un puntaje de 0 a 100 con penalizaciones ponderadas por categoría y volumen de código.
- **Reporte HTML**: genera un informe visual self-contained con metodología, detalles por módulo y divergencias de core.

---

## Categorías de módulos

| Categoría | Descripción |
|---|---|
| **Gradle JAR** | Dependencias resueltas como binarios por Gradle (`build/etendo/modules/`). Migración = bump de versión. |
| **Gradle Sources** | Módulos con fuente en `/modules/` cuyo bundle está declarado en `build.gradle`. |
| **Local Mantenido** | Fuente en `/modules/`, reconocido en el catálogo de Etendo pero sin bundle Gradle. |
| **Local sin Mantenimiento** | Fuente en `/modules/` no reconocido en el catálogo de Etendo. Requiere evaluación manual. |
| **Customización** | Módulo propio del cliente. Penalización escalonada por volumen de código (LOC). |

---

## Estructura del proyecto

```
etendo-migration-agent/
├── analyze.py                        # Entrada principal CLI
├── report_html.py                    # Genera reporte HTML desde el JSON
├── analyzer/
│   ├── version_detector.py           # Detecta plataforma y versión de core
│   ├── module_classifier.py          # Clasifica módulos por categoría
│   ├── core_diff.py                  # Compara core contra base limpia (zip)
│   ├── module_diff.py                # Compara módulos contra base limpia (zip)
│   └── migration_scorer.py           # Calcula score y breakdown de penalizaciones
├── runner/
│   └── ssh_runner.py                 # Despliega y ejecuta el analyzer vía SSH
├── data/
│   ├── supported_modules.json        # Catálogo de 174 módulos soportados por Etendo
│   ├── etendo-base/
│   │   └── etendo-core-25.4.11.zip   # Base de comparación del core
│   └── modules-base/
│       └── etendo-modules-latest.zip # Base de comparación de módulos soportados
├── docs/
│   └── manual_guide.md               # Guía de ejecución manual sin SSH
└── requirements.txt
```

---

## Uso

### 1. Directamente en el servidor del cliente

Copiar el repositorio completo al servidor y ejecutar:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre del Cliente" --output reporte.json
```

Luego, opcionalmente, generar el reporte HTML desde la misma máquina o desde local:

```bash
python3 report_html.py --input reporte.json --output reporte.html
```

### 2. Vía SSH (desde tu máquina local)

El runner despliega el analyzer en el servidor del cliente, lo ejecuta y recupera el JSON:

```bash
python runner/ssh_runner.py <hostname> <ruta_etendo> \
  --user <usuario_ssh> \
  --client "Nombre del Cliente" \
  [--key <ruta_clave_privada>] \
  [--port 22] \
  [--output-dir ./reports]
```

Ver `docs/manual_guide.md` para instrucciones detalladas.

---

## Formato del reporte JSON

```json
{
  "client": {
    "name": "Nombre del Cliente",
    "hostname": "servidor.cliente.com"
  },
  "platform": {
    "type": "etendo",
    "version": "24.2.6"
  },
  "modules": {
    "gradle_jar":           [...],
    "gradle_source":        [...],
    "local_maintained":     [...],
    "local_not_maintained": [...],
    "custom":               [...]
  },
  "core_divergences": {
    "status": "modified",
    "base_version": "25.4.11",
    "modified_files": 700,
    "diff_lines_added": 2795,
    "diff_lines_removed": 5517,
    "files": [...]
  },
  "migration_score": 17,
  "migratability": "very_hard",
  "score_breakdown": {
    "core_divergences": -40.0,
    "local_not_maintained": -20,
    "custom_modules": -9,
    "local_maintained_divergences": -14.2,
    "gradle_source_divergences": -4.7,
    "jar_dependency_outdated": -3.0
  }
}
```

---

## Score de migración

El score parte de **100** y se le restan penalizaciones por cada factor de riesgo.

| Score | Nivel | Significado |
|---|---|---|
| 80–100 | Fácil | Migración directa, principalmente actualizaciones de versión. |
| 60–79 | Moderada | Requiere trabajo de adaptación pero es manejable. |
| 40–59 | Difícil | Presencia significativa de customizaciones o módulos no mantenidos. |
| 0–39 | Muy difícil | Customizaciones extensas o core muy divergente. |

Las customizaciones se ponderan por volumen de código (LOC):

| Tamaño | LOC | Penalización |
|---|---|---|
| micro | < 500 | −1 |
| small | 500–2.000 | −4 |
| medium | 2.000–8.000 | −9 |
| large | > 8.000 | −16 |

---

## Requisitos

- Python 3.8+ (sin dependencias externas para el analyzer)
- `paramiko` únicamente si se usa el runner SSH (`pip install -r requirements.txt`)
