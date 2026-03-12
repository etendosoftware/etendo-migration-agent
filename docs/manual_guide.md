# Guía de ejecución manual — Etendo Migration Agent

Usá esta guía cuando necesites ejecutar el analyzer directamente en el servidor del cliente, sin usar el runner SSH.

## Cuándo usar este método

- No hay acceso SSH directo desde tu máquina al servidor del cliente
- El cliente prefiere ejecutar el script por su cuenta y entregar el reporte
- Entorno de red restringido

## Requisitos previos

- Python 3.8+ instalado en el servidor
- Acceso al directorio raíz de la instalación de Etendo
- `psycopg2` instalado (opcional, para incluir métricas de base de datos)

```bash
pip install psycopg2-binary   # opcional
```

## Pasos

### 1. Copiar el analyzer al servidor

Copiá el directorio `analyzer/` completo al servidor del cliente. Podés usar SCP, SFTP, o cualquier otro medio:

```bash
scp -r analyzer/ usuario@servidor:/tmp/etendo_analyzer/
```

### 2. Ejecutar el diagnóstico

En el servidor del cliente:

```bash
python3 /tmp/etendo_analyzer/etendo_diagnose.py \
  --path /ruta/a/la/instalacion/etendo \
  --output /tmp/reporte.json
```

Opciones disponibles:

| Opción | Descripción | Por defecto |
|--------|-------------|-------------|
| `--path` | Ruta raíz de la instalación Etendo | Directorio actual |
| `--output` | Archivo de salida del reporte JSON | `etendo_report.json` |
| `--db-host` | Host de PostgreSQL | `localhost` |
| `--db-port` | Puerto de PostgreSQL | `5432` |
| `--db-name` | Nombre de la base de datos | — |
| `--db-user` | Usuario de la base de datos | — |
| `--db-password` | Contraseña de la base de datos | — |

### 3. Recuperar el reporte

Una vez generado, descargá el archivo JSON:

```bash
scp usuario@servidor:/tmp/reporte.json ./output/cliente.json
```

### 4. Entregar al dashboard

Colocá el archivo en el directorio `data/reports/` del proyecto `etendo-migration-dashboard`.

## Formato del reporte generado

```json
{
  "client_id": "...",
  "etendo_version": "...",
  "modules": [
    {
      "java_package": "com.etendoerp.advanced.security",
      "type": "official",
      "bundle": "com.etendoerp.platform.extensions"
    }
  ],
  "core_alterations": [
    {
      "path": "src/org/openbravo/...",
      "expected": "sha256...",
      "actual": "sha256..."
    }
  ],
  "migration_score": 0.35,
  "migratable": true
}
```

### Interpretación del `migration_score`

| Rango | Significado |
|-------|-------------|
| 0.0 – 0.2 | Instalación limpia, migración directa |
| 0.2 – 0.5 | Customizaciones menores, migración con esfuerzo bajo |
| 0.5 – 0.8 | Customizaciones significativas, requiere análisis profundo |
| 0.8 – 1.0 | Altamente customizado, migración compleja |

## Limpieza

Después de obtener el reporte, podés eliminar el analyzer del servidor del cliente:

```bash
rm -rf /tmp/etendo_analyzer/
```
