# OBSINF

Plataforma multiempresa de observabilidad inteligente que integra información de distintas tecnologías de infraestructura, detecta comportamientos relevantes y permite analizar la operación mediante reportes y consultas conversacionales.

## Estado actual

Implementado:

- Administración de empresas y fuentes de datos.
- Catálogo de tecnologías.
- Recepción de archivos con manifiesto e idempotencia.
- Consulta del estado de los lotes y errores de ingesta.
- Procesamiento de métricas JSONL y logs de WebLogic.
- Almacenamiento y consulta de métricas y eventos normalizados.
- Configuración y activación de perfiles de normalidad.
- Detección de desviaciones mediante reglas Python.
- Persistencia de ejecuciones, evidencias y referencias a métricas.
- Interpretación de evidencias mediante un agente ADK conectado a OpenAI.
- Persistencia de hallazgos y sus evidencias.

Los reportes y las consultas conversacionales forman parte de la evolución prevista.

## Tecnologías

- Python 3.12.
- FastAPI.
- PostgreSQL.
- SQLAlchemy.
- Alembic.
- Google ADK con OpenAI.
- pytest.

## Estructura del proyecto

| Carpeta | Contenido |
| --- | --- |
| `app/agents/` | Agentes y preparación de sus instrucciones |
| `app/analysis/` | Detectores y contratos de análisis |
| `app/api/` | Endpoints y dependencias de la API |
| `app/core/` | Configuración general |
| `app/db/` | Base declarativa y sesiones de base de datos |
| `app/integrations/` | Parsers por tecnología y formato |
| `app/jobs/` | Comandos de procesamiento y análisis |
| `app/models/` | Modelos SQLAlchemy |
| `app/schemas/` | Contratos de entrada y salida |
| `app/services/` | Lógica de negocio |
| `migrations/` | Migraciones de base de datos |
| `prompts/` | Instrucciones de los agentes |
| `scripts/` | Utilidades de administración |
| `spec/` | Arquitectura, modelo de datos y especificaciones |
| `tests/` | Pruebas unitarias y de integración |
| `data/` | Archivos locales; excluidos de Git |

## Requisitos

- Python 3.12 instalado.
- PostgreSQL disponible.
- Git.
- Credenciales de OpenAI para ejecutar el agente.

Las instrucciones siguientes utilizan PowerShell en Windows.

## Instalación inicial

Clonar el repositorio:

```powershell
git clone https://github.com/sergiosalinasr/obsinf.git
cd obsinf
```

Crear y activar el entorno virtual:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instalar el proyecto y las dependencias de desarrollo:

```powershell
python -m pip install -e ".[dev]"
```

## Configuración

Crear el archivo de configuración local:

```powershell
Copy-Item .env.example .env
```

Editar `.env` con los valores del entorno. Ejemplo:

```dotenv
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=openai/gpt-5-mini

PGHOST=localhost
PGPORT=5433
PGDATABASE=obsinf
PGUSER=root
PGPASSWORD=your_postgres_password
```

El puerto, la base de datos y el usuario deben coincidir con la instalación de PostgreSQL.

No subir `.env`, claves, contraseñas ni datos reales de empresas a GitHub.

## Base de datos

Crear previamente la base de datos en PostgreSQL.

Aplicar las migraciones a la base configurada en `.env`:

```powershell
python -m alembic upgrade head
```

Consultar la revisión aplicada:

```powershell
python -m alembic current
```

Las migraciones versionan la estructura de la base de datos. El contenido de PostgreSQL no se almacena en Git.

## Iniciar a trabajar

Desde la carpeta `obsinf`, activar el entorno:

```powershell
.\.venv\Scripts\Activate.ps1
```

Iniciar el servidor de desarrollo:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Detenerlo con `Ctrl+C`.

## Documentación de la API

Con el servidor iniciado:

- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

Para utilizar Postman, importar la URL de OpenAPI.

## Procesamiento de ingestas

La recepción de archivos registra un lote pendiente. El procesamiento se ejecuta mediante el comando:

```powershell
python -m app.jobs.process_ingestion --company-id 1 --batch-id 1
```

Reemplazar los identificadores por los del lote recibido.

En las cargas multipart, `files` debe contener el archivo adjunto, no una cadena con su ruta.

## Análisis de normalidad

Para analizar métricas se necesita un perfil activo con reglas configuradas.

Ejemplo:

```powershell
python -m app.jobs.analyze_baseline `
  --company-id 1 `
  --profile-id 1 `
  --from "2026-10-27T09:00:00-03:00" `
  --to "2026-10-27T09:08:00-03:00"
```

El análisis guarda la ejecución, su cobertura, las evidencias detectadas y sus referencias a métricas.

La ausencia de datos no debe interpretarse como operación normal.

## Interpretación con el agente WebLogic

Ejecutar en modo de prueba, sin guardar hallazgos:

```powershell
python -m app.jobs.interpret_weblogic `
  --company-id 1 `
  --execution-id 1 `
  --source-id 2
```

Ejecutar y guardar los hallazgos:

```powershell
python -m app.jobs.interpret_weblogic `
  --company-id 1 `
  --execution-id 1 `
  --source-id 2 `
  --persist
```

Reemplazar los identificadores según los datos disponibles.

El agente interpreta evidencias. Las hipótesis generadas no constituyen confirmación de causa raíz ni de impacto operativo.

La ejecución del agente requiere credenciales válidas y puede generar consumo facturable de OpenAI.

## Pruebas

Las pruebas de integración utilizan una base PostgreSQL independiente llamada `obsinf_test`.

Crear esta base previamente y revisar la configuración de pruebas en `tests/integration/conftest.py`.

Aplicar sus migraciones:

```powershell
python scripts/migrate_test_db.py
```

Ejecutar todas las pruebas:

```powershell
python -m pytest -v
```

Ejecutar solo las pruebas unitarias:

```powershell
python -m pytest tests/unit -v
```

No utilizar una base con datos operativos como destino de las pruebas.

## Documentación técnica

- [Arquitectura](spec/architecture.md)
- [Modelo de datos](spec/data-model.md)
- [Ingesta por empresa y fuente](spec/features/001-company-source-ingestion.md)

## Actualizar el repositorio

Revisar, guardar y subir los cambios:

```powershell
git status
git add .
git diff --cached --stat
git commit -m "Descripción del cambio"
git push
```

Verificar los archivos preparados antes de confirmar, especialmente ante cambios de configuración o incorporación de datos.