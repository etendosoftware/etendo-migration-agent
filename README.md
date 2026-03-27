# etendo-migration-agent

Herramienta de análisis de instalaciones Etendo/Openbravo on-premise para estimar el esfuerzo de migración a SaaS. Se ejecuta una vez en el servidor del cliente y genera un reporte JSON + HTML con el diagnóstico completo.

**Requiere únicamente Python 3.8+. Sin dependencias externas.**

---

## ¿Qué analiza?

- **Plataforma y versión**: detecta si la instalación es Etendo o Openbravo, y la versión de core instalada.
- **Módulos**: clasifica todos los módulos en 5 categorías según su origen y forma de gestión.
- **Divergencias en core y módulos**: compara los archivos fuente del cliente contra una base limpia para detectar diferencias reales (customizaciones). El modo recomendado expande dinámicamente la versión exacta instalada via `./gradlew expand`, eliminando el ruido por gap de versión. Si no es posible, usa un zip estático como fallback.
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
│   ├── core_diff.py                  # Compara core contra baseline (expandido o zip)
│   ├── module_diff.py                # Compara módulos contra baseline (expandido o zip)
│   ├── baseline_expander.py          # Genera build.gradle dinámico y corre ./gradlew expand
│   └── migration_scorer.py           # Calcula score y breakdown de penalizaciones
├── runner/
│   └── ssh_runner.py                 # Despliega y ejecuta el analyzer vía SSH
├── data/
│   ├── supported_modules.json        # Catálogo de 174 módulos soportados por Etendo
│   ├── etendo-base/
│   │   └── etendo-core-25.4.11.zip   # Baseline estático de fallback para core
│   └── modules-base/
│       └── etendo-modules-latest.zip # Baseline estático de fallback para módulos
├── docs/
│   └── manual_guide.md               # Guía de ejecución manual sin SSH
└── requirements.txt
```

---

## Uso

### 1. Análisis básico (fallback a zips estáticos)

El modo más simple. El diff se hace contra los zips empaquetados en `data/`, que corresponden a la última versión publicada. Útil para una primera aproximación rápida.

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre del Cliente" --output reporte.json
```

### 2. Análisis con baseline exacto (recomendado)

Genera dinámicamente un `build.gradle` con las versiones instaladas del cliente, corre `./gradlew expand` para obtener el código fuente exacto, y usa eso como base de comparación. Esto elimina el ruido por gap de versión y mide solo las customizaciones reales.

Requiere que las credenciales de GitHub estén en el `gradle.properties` de la instalación (`githubUser` / `githubToken`), o pasarlas por CLI:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre del Cliente" \
  --output reporte.json \
  --expand-baseline
```

Con credenciales explícitas:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre del Cliente" \
  --output reporte.json \
  --expand-baseline \
  --github-user miusuario \
  --github-token ghp_xxx \
  --verbose
```

Si la expansión falla (OOM, sin credenciales, timeout), el análisis continúa automáticamente usando el zip estático como fallback.

### 3. Reutilizar un baseline ya expandido

Si ya corriste `--expand-baseline` antes y querés evitar el tiempo de descarga, podés apuntar al directorio expandido directamente:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre del Cliente" \
  --output reporte.json \
  --baseline-dir /tmp/etendo-baseline-xyz
```

### 4. Generar el reporte HTML

```bash
python3 report_html.py --input reporte.json --output reporte.html
```

### 5. Vía SSH (desde tu máquina local)

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

## Cómo funciona el baseline expandido

El `baseline_expander.py` implementa la siguiente estrategia:

1. Lee las credenciales de GitHub del `gradle.properties` del cliente.
2. Detecta la versión del plugin Etendo Gradle desde el `build.gradle` del cliente.
3. Detecta los bundles instalados y sus versiones exactas (desde `AD_MODULE.xml`).
4. Genera un `build.gradle` mínimo con `supportJars=false` y las dependencias `moduleDeps` en las versiones instaladas.
5. Copia el Gradle wrapper del cliente (cada instalación puede tener una versión diferente).
6. Genera un `settings.gradle` con el repositorio del plugin de Etendo.
7. Corre `yes Y | ./gradlew expand` en un directorio temporal.
8. Devuelve el directorio con el código fuente expandido, que se usa como base del diff.

El formato de cada dependencia en el `build.gradle` dinámico es:
```groovy
moduleDeps('com.etendoerp:financial.extensions:1.4.2@zip'){transitive=true}
```

El `@zip` le indica a Gradle que resuelva el artefacto como fuente (zip), no como JAR.

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
    "base_version": "24.2.6",
    "baseline_type": "expanded",
    "modified_files": 79,
    "diff_lines_added": 1200,
    "diff_lines_removed": 800,
    "files": [...]
  },
  "migration_score": 67,
  "migratability": "moderate",
  "score_breakdown": {
    "openbravo_platform": 0,
    "core_divergences": -12,
    "core_diff_lines": 3925,
    "local_not_maintained": -20,
    "custom_modules": -1,
    "custom_modules_detail": [...],
    "local_maintained_divergences": 0,
    "gradle_source_divergences": 0,
    "jar_dependency_outdated": 0
  }
}
```

El campo `baseline_type` indica el origen del baseline usado: `"expanded"` (versión exacta via gradlew) o `"zip"` (fallback estático).

---

## Score de migración

El score parte de **100** y se le restan penalizaciones basadas en **volumen de código customizado** (líneas de diff), no en cantidad de archivos.

| Score | Nivel | Significado |
|---|---|---|
| 80–100 | Fácil | Migración directa, principalmente actualizaciones de versión. |
| 60–79 | Moderada | Requiere trabajo de adaptación pero es manejable. |
| 40–59 | Difícil | Presencia significativa de customizaciones o módulos no mantenidos. |
| 0–39 | Muy difícil | Customizaciones extensas o core muy divergente. |

### Penalizaciones

**Plataforma Openbravo:** −20 fijo.

**Divergencias en core** (líneas diff añadidas + eliminadas):

| Volumen | Penalización |
|---|---|
| < 1.000 líneas | −5 |
| 1.000 – 5.000 líneas | −12 |
| 5.000 – 20.000 líneas | −20 |
| > 20.000 líneas | −25 (cap) |

> Nota: con baseline ZIP estático (fallback), el diff incluye cambios propios de la diferencia de versión. La penalización es más precisa cuando se usa `--expand-baseline`.

**Módulos sin mantenimiento:** −3 por módulo (cap −20).

**Módulos de customización** (LOC total del módulo):

| Tamaño | LOC | Penalización |
|---|---|---|
| micro | < 500 | −1 |
| small | 500 – 2.000 | −4 |
| medium | 2.000 – 8.000 | −9 |
| large | > 8.000 | −16 |
| — | cap global | −35 |

**Módulos mantenidos con código customizado** (líneas diff por módulo):

| Volumen diff | Penalización |
|---|---|
| 0 – 50 líneas | 0 (ruido/formato) |
| 50 – 200 líneas | −1 |
| 200 – 1.000 líneas | −3 |
| 1.000 – 5.000 líneas | −6 |
| > 5.000 líneas | −10 |
| — | cap global −15 |

**No penalizan:** módulos Gradle Source desactualizados (actualización simple) ni dependencias JAR desactualizadas (señal positiva de gestión con Gradle).

---

## Requisitos

- Python 3.8+ (sin dependencias externas para el analyzer)
- `paramiko` únicamente si se usa el runner SSH (`pip install -r requirements.txt`)
- Para `--expand-baseline`: credenciales de GitHub con acceso al registry de Etendo y la instalación debe tener el Gradle wrapper (`gradlew`)
