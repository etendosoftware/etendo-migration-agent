# etendo-migration-agent

Agente que se ejecuta en servidores on-premise de clientes Etendo para analizar el estado de la instalación y estimar el esfuerzo de migración a SaaS.

## ¿Qué hace?

- Detecta la versión instalada de Etendo ERP
- Inventaria y clasifica los módulos (core, extensiones oficiales, customizaciones de terceros)
- Detecta alteraciones en archivos del core mediante comparación de checksums
- Calcula métricas de customización (tablas, columnas, ventanas, procesos adicionales)
- Mapea el impacto funcional por área del ERP
- Genera un score de migración y un reporte JSON listo para ser consumido por el dashboard

## Estructura del proyecto

```
etendo-migration-agent/
├── analyzer/
│   ├── etendo_diagnose.py        # Script principal de diagnóstico
│   ├── module_classifier.py      # Clasificador de módulos por tipo de origen
│   ├── tampering_detector.py     # Detector de alteraciones en archivos core
│   └── functional_areas.json     # Mapeo de módulos a áreas funcionales
├── runner/
│   └── ssh_runner.py             # Despliega y ejecuta el analyzer vía SSH
├── data/
│   └── supported_modules.json    # Lista de módulos oficiales soportados por Etendo
├── docs/
│   └── manual_guide.md           # Guía para ejecución manual sin SSH
└── requirements.txt
```

## Modos de ejecución

### 1. Automático via SSH (recomendado)

Desde tu máquina local, el runner se conecta al servidor del cliente, despliega el analyzer, lo ejecuta y recupera el reporte JSON:

```bash
python runner/ssh_runner.py <hostname> <ruta_etendo> \
  --user <usuario_ssh> \
  [--key <ruta_clave_privada>] \
  [--password <contraseña>] \
  [--port 22] \
  [--output-dir ./output]
```

Ejemplo:

```bash
python runner/ssh_runner.py 192.168.1.100 /opt/etendo \
  --user admin \
  --key ~/.ssh/id_rsa
```

El reporte se guarda en `output/<hostname>.json`.

### 2. Manual en el servidor del cliente

Si no hay acceso SSH directo, copiá el directorio `analyzer/` al servidor y ejecutá:

```bash
python3 etendo_diagnose.py --path /ruta/a/etendo --output reporte.json
```

Ver `docs/manual_guide.md` para instrucciones detalladas.

## Instalación de dependencias

```bash
pip install -r requirements.txt
```

## Formato del reporte generado

```json
{
  "client_id": "...",
  "etendo_version": "...",
  "modules": [...],
  "core_alterations": [...],
  "migration_score": 0.0,
  "migratable": true
}
```

El reporte JSON se entrega al dashboard (`etendo-migration-dashboard`) para su visualización.

## Requisitos

- Python 3.8+
- Acceso SSH al servidor del cliente (modo automático) o acceso directo (modo manual)
- `paramiko` para el runner SSH
- `psycopg2` opcional para consultas a la base de datos PostgreSQL
