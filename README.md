# etendo-migration-agent

Herramienta de análisis de instalaciones Etendo/Openbravo on-premise para estimar el esfuerzo de migración a SaaS. Genera un reporte JSON + HTML con diagnóstico técnico completo: módulos, divergencias de core, score de migrabilidad, assessment profundo de customizaciones y análisis de preparación para la nueva UI de Etendo.

---

## Primeros pasos

### 1. Clonar el repositorio

```bash
git clone git@github.com:etendosoftware/etendo-migration-agent.git
cd etendo-migration-agent
```

### 2. Abrir Claude Code en el directorio raíz

```bash
claude
```

Las skills del proyecto (`.claude/skills/`) se cargan automáticamente al iniciar Claude Code en este directorio.

---

## Requisitos

- Python 3.8+ (sin dependencias externas)
- Para el Paso 2: credenciales de GitHub con acceso al registry de Etendo y Gradle wrapper (`gradlew`) en la instalación del cliente
- Para los Pasos 5 y 6: Claude Code corriendo en el directorio raíz del proyecto (las skills se incluyen en `.claude/skills/`)
- Para el Paso 6: MCP de Mixpanel configurado en Claude Code (ver abajo)

### Configuración del MCP de Mixpanel

El Paso 6 requiere el MCP de Mixpanel conectado a Claude Code como **integración web personalizada** (no como MCP local).

**Pasos para configurarlo:**

1. Iniciar sesión en Mixpanel EU: https://eu.mixpanel.com/ con el usuario `isaias.battaglia@etendo.software`
2. Abrir Claude Code (claude.ai) → **Settings → Integrations**
3. Agregar una integración personalizada con los siguientes datos:
   - **Nombre:** `Mixpanel EU`
   - **Tipo:** Personalizado
   - **URL:** `https://mcp-eu.mixpanel.com/mcp`
4. Claude Code generará un link de autenticación — abrirlo y autorizar el acceso a la cuenta de Mixpanel
5. Una vez autenticado, la integración queda disponible en todas las sesiones de Claude Code como `mcp__claude_ai_Mixpanel_EU__*`

---

## ¿Qué analiza?

| Sección | Descripción |
|---|---|
| **Plataforma y versión** | Detecta si la instalación es Etendo o Openbravo, y la versión exacta de core. |
| **Clasificación de módulos** | Clasifica todos los módulos en 5 categorías según su origen y forma de gestión. |
| **Divergencias de core** | Compara el código fuente del cliente contra una base limpia para medir customizaciones reales. |
| **Score de migración** | Puntaje 0–100 con penalizaciones ponderadas por categoría y volumen de código. |
| **Custom Assessment** | Análisis profundo (vía agente IA) de cada customización: qué hace, si puede subirse a core, esfuerzo estimado. |
| **UI Readiness** | Análisis (vía agente IA) de qué features pendientes de la nueva UI son críticas para este cliente específico, basado en el código fuente instalado. |
| **Uso real (Mixpanel)** | Cruce de módulos custom y sin mantenimiento contra datos reales de uso en producción: score de actividad, ventanas usadas, y candidatos a eliminación antes de migrar. |

---

## Flujo completo de análisis

El análisis se realiza en **7 etapas** en orden. Los pasos 1–4 son automáticos (CLI); los pasos 5–6 los ejecuta el agente IA de Claude; el paso 7 refresca el dashboard global.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  0. Clonar repo + abrir Claude Code en el directorio raíz                │
│  1. Setup baseline      analyze.py --setup-baseline                      │
│  2. Expandir módulos    ./gradlew expandCore + ./gradlew expandModules   │
│  3. Generar JSON        analyze.py --baseline-dir ...                    │
│  4. Generar HTML        report_html.py                                   │
│  5. Assessment IA       /etendo-customisation-expert <cliente>           │
│  6. Análisis de uso     /etendo-mixpanel-usage <cliente>                 │
│  7. Refrescar dashboard python3 dashboard.py                             │
│  ── automático ──────────────────────────────────────────────────────── │
│  8. Análisis portfolio  se ejecuta automáticamente tras cada Paso 5 o 6 │
│     (o manualmente:     python3 scripts/portfolio_analysis.py)           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Paso 1 — Setup del baseline

Genera el `build.gradle` dinámico con las versiones exactas instaladas del cliente y muestra los comandos a ejecutar:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre Cliente" --setup-baseline
```

Salida: crea un directorio en `baselines/etendo-baseline-<hash>/` dentro del proyecto e imprime los comandos del paso siguiente.

### Paso 2 — Expandir módulos

Ejecutar en el directorio del baseline generado en el paso anterior:

```bash
./gradlew expandCore
```
```bash
./gradlew expandModules
```

Esto descarga el código fuente exacto de las versiones instaladas del cliente. Requiere que `gradle.properties` tenga las credenciales de GitHub (`githubUser` / `githubToken`) o pasarlas por CLI.

### Paso 3 — Generar el reporte JSON

```bash
python3 analyze.py \
  --path /ruta/a/etendo \
  --client "Nombre Cliente" \
  --output reports/cliente.json \
  --baseline-dir baselines/etendo-baseline-<hash>
```

Con credenciales explícitas:

```bash
python3 analyze.py \
  --path /ruta/a/etendo \
  --client "Nombre Cliente" \
  --output reports/cliente.json \
  --baseline-dir baselines/etendo-baseline-<hash> \
  --github-user miusuario \
  --github-token ghp_xxx \
  --verbose
```

> Si no hay baseline expandido disponible, el análisis cae automáticamente al zip estático en `data/etendo-base/`. contra Etendo 25.4. En ese caso el diff incluye ruido de gap de versión; la penalización es mucho menos precisa.

### Paso 4 — Generar el reporte HTML

```bash
python3 report_html.py --input reports/cliente.json --output reports/cliente.html
```

### Paso 5 — Assessment profundo con el agente IA

Este paso genera las secciones `custom_assessment` y `ui_readiness` del JSON. Se ejecuta desde Claude Code:

```
/etendo-customisation-expert cliente
```

El agente realiza:
1. **Análisis de core**: lee cada archivo customizado, determina si debe subirse a core upstream, ya existe en versiones nuevas, o debe eliminarse.
2. **Análisis de módulos custom**: describe qué hace cada módulo en términos de negocio, evalúa si es generalizable como bundle oficial.
3. **Análisis de módulos sin mantenimiento**: evalúa riesgo de migración y existencia de reemplazo oficial.
4. **UI Readiness**: para cada feature pendiente de la nueva UI de Etendo, determina si este cliente la necesita analizando el código fuente en `src/`, `modules/` y `modules_core/`. Las dependencias en JAR se ignoran.
5. Escribe ambas secciones al JSON y regenera el HTML.

### Paso 6 — Análisis de uso real con Mixpanel

Este paso enriquece el `custom_assessment` con datos reales de uso en producción. Requiere el **MCP de Mixpanel** configurado (ver [Requisitos](#requisitos)).

```
/etendo-mixpanel-usage cliente
```

Opcionalmente, si el nombre de la instancia en Mixpanel difiere del nombre del cliente:

```
/etendo-mixpanel-usage cliente nombre-instancia-mixpanel
```

El agente realiza:
1. **Extracción de ventanas por módulo**: lee los `AD_WINDOW.xml` y `AD_PROCESS.xml` de cada módulo custom y sin mantenimiento para obtener los nombres exactos de ventanas y procesos definidos.
2. **Consulta a Mixpanel**: para cada ventana/proceso, cuenta los eventos de los últimos 90 días en el entorno de producción del cliente.
3. **Scoring de uso** (escala 0–5): 0 = sin uso, 5 = > 10.000 eventos.
4. **Candidatos a eliminación**: módulos con score 0 y sin potencial de generalización se marcan como `elimination_candidate`.
5. Actualiza el JSON con `usage_score`, `windows_used`, `windows_unused` por módulo y estadísticas de ahorro de esfuerzo, y regenera el HTML.

### Paso 7 — Refrescar el dashboard

Después de agregar o actualizar cualquier cliente, regenerar el dashboard agregado:

```bash
python3 dashboard.py
```

Genera `reports/dashboard.html` con el ranking actualizado de todos los clientes.

### Paso 8 — Análisis de portfolio (automático)

Este paso se ejecuta **automáticamente** cada vez que los Pasos 5 o 6 actualizan un `reports/*.json`. No requiere intervención manual.

Si se quiere ejecutar manualmente:

```bash
python3 scripts/portfolio_analysis.py
```

O desde Claude Code:

```
/etendo-portfolio-analysis
```

El análisis escanea todos los reportes que tienen `custom_assessment` y/o `ui_readiness` completos, y agrega tres secciones al final del dashboard:

| Sección | Descripción |
|---|---|
| **Preparación para nueva UI** | Ranking de clientes por UI Score (0–100) con los principales bloqueadores por cliente. |
| **Módulos sin mantenimiento** | Módulos que aparecen en múltiples clientes o son de riesgo alto sin reemplazo — candidatos a ser mantenidos oficialmente por Etendo. |
| **Customizaciones generalizables** | Modificaciones de core propuestas para upstream y módulos candidatos a bundle oficial del marketplace. |

---

## Análisis de modo directo (sin expansión)

Para una primera aproximación rápida sin necesidad de expandir el baseline:

```bash
python3 analyze.py --path /ruta/a/etendo --client "Nombre Cliente" --output reports/cliente.json
```

---

## Estructura del proyecto

```
etendo-migration-agent/
├── analyze.py                         # CLI principal — genera el JSON base
├── report_html.py                     # Genera reporte HTML desde el JSON
├── dashboard.py                       # Dashboard agregado de todos los clientes
├── scripts/
│   └── portfolio_analysis.py          # Análisis cruzado de portfolio (ejecutado por hook automático)
├── analyzer/
│   ├── version_detector.py            # Detecta plataforma y versión de core
│   ├── module_classifier.py           # Clasifica módulos por categoría
│   ├── core_diff.py                   # Compara core contra baseline
│   ├── module_diff.py                 # Compara módulos contra baseline
│   ├── baseline_expander.py           # Genera build.gradle dinámico y corre gradlew expand
│   ├── migration_scorer.py            # Calcula score y breakdown de penalizaciones
│   └── tampering_detector.py         # Detecta alteraciones fuera del flujo git
├── data/
│   ├── supported_modules.json         # Catálogo de módulos soportados por Etendo
│   ├── ui_feature_map.json            # Mapa estático: features pendientes → code signatures
│   ├── all-features.md                # Listado completo de features de la nueva UI
│   ├── all-features-analysis.md       # Análisis de completitud de la nueva UI (~62% global)
│   ├── etendo-base/
│   │   └── etendo-core-*.zip          # Baseline estático de fallback para core
│   └── modules-base/
│       └── etendo-modules-latest.zip  # Baseline estático de fallback para módulos
├── reports/
│   ├── cliente.json                   # Reporte JSON de cada cliente
│   └── cliente.html                   # Reporte HTML de cada cliente
├── docs/
│   └── manual_guide.md                # Guía de ejecución manual sin SSH
└── requirements.txt
```

---

## Formato del reporte JSON

El JSON final tiene 4 secciones principales. Las dos últimas las agrega el agente IA en el Paso 5.

```json
{
  "client": { "name": "...", "hostname": "..." },
  "platform": { "type": "etendo", "version": "24.2.6" },
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
  "score_breakdown": { ... },

  "custom_assessment": {
    "assessor_version": "1.0",
    "generated": "2026-04-06",
    "mixpanel_source_instance": "nombre-instancia",   // agregado por el Paso 6
    "mixpanel_date_range": "90 días",                 // agregado por el Paso 6
    "core_customizations": [
      {
        "name": "...",
        "description": "...",
        "files": ["..."],
        "lines_changed": 0,
        "conclusion": "upstream|already_upstream|eliminate",
        "justification": "...",
        "effort_days": "X-Y days"
      }
    ],
    "custom_modules": [
      {
        "java_package": "...",
        "name": "...",
        "description": "...",
        "generalization": "bundle_candidate|client_specific|redundant",
        "complexity": "trivial|minor|major|critical",
        "effort_days": "X-Y days",
        "recommendation": "...",
        "usage_score": 0,              // 0–5, agregado por el Paso 6
        "windows_used": [],            // ventanas con eventos en Mixpanel
        "windows_unused": [],          // ventanas sin eventos
        "elimination_candidate": true  // true si score=0 y no es bundle_candidate
      }
    ],
    "unmaintained_modules": [
      {
        "java_package": "...",
        "name": "...",
        "function": "...",
        "risk": "low|medium|high",
        "has_official_replacement": true,
        "official_replacement_name": "...",
        "generalization": "bundle_candidate|client_specific|redundant",
        "effort_days": "X-Y days",
        "recommendation": "...",
        "usage_score": 0,              // 0–5, agregado por el Paso 6
        "windows_used": [],
        "windows_unused": [],
        "elimination_candidate": false
      }
    ],
    "effort_summary": {
      "core_min": 0.0, "core_max": 0.0,
      "custom_min": 0.0, "custom_max": 0.0,
      "unmaintained_min": 0.0, "unmaintained_max": 0.0,
      "total_min": 0.0, "total_max": 0.0,
      "elimination_candidates": 0,           // agregado por el Paso 6
      "effort_saved_eliminating_min": 0.0,   // días ahorrados eliminando candidatos
      "effort_saved_eliminating_max": 0.0
    }
  },

  "ui_readiness": {
    "generated": "2026-04-06",
    "global_status": "blocked|partial|ready",
    "summary": { "critica": 6, "alta": 7, "media": 11, "no_aplica": 8 },
    "features": [
      {
        "section": "2.B.2",
        "title": "Posted Button — 3 estados contables",
        "status": "PARCIAL",
        "completion_pct": 30,
        "priority": "critica",
        "reason": "Encontrado en código: columna Posted. (14 archivo(s) afectados)",
        "code_evidence": [
          {
            "description": "Columnas con nombre Posted",
            "files": ["modules/com.etendoerp.financial.extensions/.../AD_COLUMN.xml", "..."]
          }
        ]
      }
    ]
  }
}
```

### `ui_readiness.global_status`

| Valor | Condición |
|---|---|
| `blocked` | ≥ 1 feature crítica pendiente |
| `partial` | Sin críticas, pero ≥ 3 features altas |
| `ready` | Solo medias o no aplica |

### Prioridades de UI Readiness

| Prioridad | Descripción |
|---|---|
| **crítica** | El cliente depende de esta funcionalidad y no puede operar sin ella en la nueva UI |
| **alta** | Impacta flujos de trabajo principales del cliente |
| **media** | Funcionalidad usada pero con alternativas o workarounds posibles |
| **no aplica** | No se encontró evidencia de uso en el código fuente |

El análisis siempre busca en `src/`, `modules/` y `modules_core/`. Las dependencias en JAR se excluyen porque no son evidencia confiable de uso real.

---

## Clasificación de módulos

| Categoría | Descripción |
|---|---|
| **Gradle JAR** | Dependencias resueltas como binarios por Gradle (`build/etendo/modules/`). Migración = bump de versión. |
| **Gradle Sources** | Módulos con fuente en `/modules/` cuyo bundle está declarado en `build.gradle`. |
| **Local Mantenido** | Fuente en `/modules/`, reconocido en el catálogo de Etendo pero sin bundle Gradle. |
| **Local sin Mantenimiento** | Fuente en `/modules/`, no reconocido en el catálogo de Etendo. Requiere evaluación manual. |
| **Customización** | Módulo propio del cliente. Penalización escalonada por volumen de código (LOC). |

---

## Score de migración

El score parte de **100** y se descuentan penalizaciones basadas en **volumen de código customizado** (líneas de diff), no en cantidad de archivos. La penalización máxima posible es **−100**, por lo que el score mínimo alcanzable es 0.

| Score | Nivel | Significado |
|---|---|---|
| 80–100 | Fácil | Migración directa, principalmente actualizaciones de versión. |
| 60–79 | Moderada | Requiere trabajo de adaptación pero es manejable. |
| 40–59 | Difícil | Presencia significativa de customizaciones o módulos no mantenidos. |
| 0–39 | Muy difícil | Customizaciones extensas o core muy divergente. |

### Penalizaciones

Las 5 categorías de penalización suman un cap máximo total de **−100**:

| Categoría | Criterio | Cap |
|---|---|---|
| Plataforma Openbravo | −20 fijo si la instalación es Openbravo (no Etendo) | −20 |
| Divergencias en core | −0,5 por cada 100 líneas diff (añadidas + eliminadas) | −15 |
| Módulos sin mantenimiento | −3 por módulo regular, −0,3 por pack de traducción | −20 |
| Módulos de customización | −1/−4/−9/−16 según tamaño (micro/small/medium/large) | −35 |
| Módulos mantenidos con divergencias | −1/−3/−6/−10 según volumen de diff por módulo | −10 |

**No penalizan** (son señal positiva o se resuelven con una actualización estándar):
- Módulos Gradle Source desactualizados
- Dependencias JAR desactualizadas

---

## Cómo funciona el baseline expandido

El `baseline_expander.py` implementa la siguiente estrategia:

1. Lee las credenciales de GitHub del `gradle.properties` del cliente.
2. Detecta la versión del plugin Etendo Gradle desde el `build.gradle` del cliente.
3. Detecta los bundles instalados y sus versiones exactas (desde `AD_MODULE.xml`).
4. Genera un `build.gradle` mínimo con `supportJars=false` y las dependencias `moduleDeps` en las versiones instaladas.
5. Copia el Gradle wrapper del cliente.
6. Genera un `settings.gradle` con el repositorio del plugin de Etendo.
7. Corre `yes Y | ./gradlew expand` en un directorio temporal.
8. Devuelve el directorio con el código fuente expandido, que se usa como base del diff.

Formato de cada dependencia en el `build.gradle` dinámico:

```groovy
moduleDeps('com.etendoerp:financial.extensions:1.4.2@zip'){transitive=true}
```

El `@zip` le indica a Gradle que resuelva el artefacto como fuente, no como JAR.

