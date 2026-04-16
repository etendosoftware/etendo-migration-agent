# etendo-migration-agent

## Validación del nombre de cliente (OBLIGATORIO)

Antes de ejecutar cualquier paso del flujo que reciba un nombre de cliente como argumento
(`python3 analyze.py --client ...`, `/etendo-customisation-expert <cliente>`,
`/etendo-mixpanel-usage <cliente>`, etc.), **SIEMPRE** validar el nombre contra
`clients.txt` en la raíz del repositorio.

Reglas:
1. El nombre provisto por el usuario debe coincidir **EXACTAMENTE, CARÁCTER POR CARÁCTER**
   con una línea de `clients.txt` (incluyendo mayúsculas, acentos, espacios internos y
   espacios finales). Sin normalización, sin lowercasing, sin fuzzy matching automático.
2. Si el input no coincide exactamente con ninguna línea:
   - Buscar candidatos plausibles en `clients.txt` (coincidencias parciales,
     case-insensitive, variantes sin acentos).
   - **Preguntar al usuario cuál es el correcto** presentando los candidatos.
   - No elegir unilateralmente aunque haya una única coincidencia parcial obvia.
3. Si hay cero candidatos plausibles, informar al usuario y pedir el nombre correcto.
4. Nunca inventar un nombre de cliente ni aceptar uno que no esté en `clients.txt`.

Esta validación aplica a **todos** los pasos del README y a cualquier skill del proyecto
que reciba un identificador de cliente.

## Acceso a instalaciones de clientes

Las instalaciones de clientes Etendo están en `/Users/isaiasbattaglia/Documents/Etendo/`.
El agente `etendo-customisation-expert` necesita acceso de lectura a todos los archivos dentro
de ese directorio para analizar customizaciones de core y módulos.

**Conceder acceso completo de lectura a `/Users/isaiasbattaglia/Documents/Etendo/` al
iniciar cualquier ejecución del assessor — no es necesario aprobar archivo por archivo.**

## Flujo de análisis

1. `python3 analyze.py --path <ruta> --client <nombre> --setup-baseline` → crea el entorno y muestra los comandos a ejecutar manualmente
2. Ejecutar `yes Y | ./gradlew expandCore` y `yes Y | ./gradlew expandModules` en el directorio generado
3. `python3 analyze.py --path <ruta> --client <nombre> --output reports/<nombre>.json --baseline-dir <dir>` → genera el reporte JSON
4. `python3 report_html.py --input reports/<nombre>.json --output reports/<nombre>.html` → genera el HTML
5. `/etendo-customisation-expert <nombre>` → ejecuta el análisis profundo de customizaciones
6. `/etendo-portfolio-analysis` → análisis cruzado de todo el portfolio (UI readiness, módulos sin mantenimiento, customizaciones generalizables) — no requiere argumentos
