# etendo-migration-agent

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
