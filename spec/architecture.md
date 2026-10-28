# OBSINF — Arquitectura

Estado: definición inicial
Fecha: 2026-10-19

## 1. Propósito

OBSINF — Observador de Infraestructura — es una plataforma
multiempresa de observabilidad inteligente que integra información
de distintas tecnologías de infraestructura, detecta comportamientos
relevantes y permite analizar la operación mediante reportes y
consultas conversacionales.

Es una aplicación independiente de observability-ai-poc.
La POC se conserva sin modificaciones como referencia.

## 2. Alcance funcional

- Administrar empresas y sus fuentes de información.
- Incorporar métricas, eventos y logs.
- Conservar los archivos originales y normalizar su contenido.
- Detectar comportamientos relevantes mediante reglas y cálculos.
- Correlacionar evidencias de distintas fuentes.
- Generar reportes de las últimas n horas por empresa.
- Responder consultas conversacionales sustentadas en evidencias.
- Registrar cargas, análisis y reportes para mantener trazabilidad.

La incorporación de tecnologías será incremental.
La primera integración será WebLogic mediante carga de archivos.

## 3. Arquitectura general

Se implementará un monolito modular en Python.

La API y los procesos de trabajo compartirán módulos de negocio,
pero podrán ejecutarse como procesos independientes.

Componentes:

1. API FastAPI: recibe solicitudes y aplica autenticación,
   autorización y validación.
2. Servicios: implementan los casos de uso.
3. Integraciones: interpretan formatos específicos de cada fuente.
4. Análisis: calcula estadísticas, evalúa reglas y genera hallazgos.
5. Agentes ADK: consultan evidencias, correlacionan y explican.
6. PostgreSQL: almacena información estructurada y trazabilidad.
7. Almacenamiento de archivos: conserva originales y exportaciones.
8. Procesos programados: ejecutan ingestas, análisis y reportes.

Inicialmente, la API será la interfaz de acceso.
La interfaz gráfica se definirá en una etapa posterior.

## 4. Stack inicial

- Python.
- FastAPI y Uvicorn.
- Google ADK.
- OpenAI como proveedor inicial del modelo.
- PostgreSQL.
- SQLAlchemy y psycopg.
- Alembic para migraciones.
- Pydantic y Pydantic Settings.
- pytest y httpx.
- Docker Compose para los servicios locales.

Las versiones compatibles se fijarán durante la preparación
del entorno y se registrarán en las dependencias del proyecto.

## 5. Estructura del proyecto

obsinf/
├── app/
│   ├── main.py
│   ├── api/v1/endpoints/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── integrations/
│   ├── analysis/
│   ├── agents/
│   │   ├── coordinator/
│   │   ├── infrastructure/
│   │   └── tools/
│   └── jobs/
├── migrations/
├── tests/
│   ├── unit/
│   └── integration/
├── spec/
│   ├── architecture.md
│   ├── data-model.md
│   └── features/
├── scripts/
├── data/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md

## 6. Separación por empresa

Se utilizará inicialmente una base de datos y un esquema compartidos.

La clave primaria de empresa será BIGINT GENERATED ALWAYS AS IDENTITY.
Las entidades pertenecientes a una empresa incluirán company_id.

Las relaciones deberán impedir referencias entre datos de empresas
distintas, mediante restricciones de integridad cuando corresponda.

El contexto de empresa se obtendrá de la identidad autenticada y
sus permisos. El company_id recibido en una petición no constituye
por sí mismo una autorización.

Los servicios, tareas y herramientas de agentes deberán operar
con un contexto de empresa explícito y validado.

Las conversaciones y sesiones de agentes también estarán aisladas
por empresa y usuario.

Los identificadores numéricos facilitan la administración y SQL;
no sustituyen los controles de acceso.

## 7. Almacenamiento de archivos

La raíz será configurable mediante OBSINF_DATA_DIR.

Estructura local:

data/companies/<company_id>/
├── incoming/
├── raw/<source_id>/<YYYY>/<MM>/<DD>/
├── rejected/
└── exports/

- incoming: archivos pendientes de procesamiento.
- raw: originales recibidos, sin sobrescribir.
- rejected: archivos rechazados y detalle de sus errores.
- exports: reportes y otras exportaciones.

Los nombres internos serán generados por el sistema para evitar
colisiones y rutas suministradas por el usuario.

PostgreSQL registrará la ubicación, tamaño, hash y estado del archivo.
El almacenamiento estará fuera del directorio público de la API.

data/ estará excluida de Git.
Los ejemplos sintéticos de prueba se mantendrán en tests/fixtures/.

En producción se podrá usar un volumen externo o almacenamiento
de objetos mediante una abstracción de almacenamiento.

## 8. Flujo de ingesta

1. Resolver y validar empresa y fuente.
2. Recibir el archivo y registrar el lote de ingesta.
3. Conservar el original y calcular su hash.
4. Validar formato y seleccionar el adaptador.
5. Interpretar y normalizar los registros.
6. Guardar métricas, eventos y logs en PostgreSQL.
7. Registrar cantidades aceptadas, rechazadas y errores.
8. Marcar el resultado del lote.

Se definirán controles de duplicados para que un reintento no
duplique observaciones ya incorporadas.

Cada registro normalizado conservará una referencia al archivo
y, cuando sea posible, a la línea o registro de origen.

Se distinguirán el momento del evento y el momento de recepción.
Las fechas se almacenarán con zona horaria y se normalizarán a UTC.
La empresa tendrá una zona horaria para presentación y programación.

## 9. Análisis y agentes

Python realizará las tareas deterministas:

- Parsing y normalización.
- Consultas y recuperación de evidencias.
- Estadísticas, umbrales y tendencias.
- Validaciones y controles de calidad.

Los agentes ADK realizarán:

- Interpretación de evidencias.
- Correlación entre fuentes.
- Elaboración de explicaciones y reportes.
- Respuestas conversacionales.

El coordinador organizará el análisis y utilizará agentes
especializados cuando el caso lo requiera.

Las herramientas entregarán datos acotados por empresa, fuente
y período. No se permitirá ejecutar SQL arbitrario generado
por el modelo.

Los agentes distinguirán hechos, hipótesis e información insuficiente.
La correlación no se presentará automáticamente como causa raíz.

Los logs y archivos se tratarán como datos no confiables:
su contenido no podrá modificar las instrucciones de los agentes.

OBSINF no ejecutará acciones correctivas sobre la infraestructura
en el alcance inicial.

## 10. Reportes y chat

El reporte matinal tendrá horario, zona horaria y ventana de
análisis configurables por empresa.

Incluirá:

- Período analizado.
- Fuentes disponibles y cobertura de datos.
- Hallazgos relevantes y su severidad.
- Evidencias y correlaciones.
- Limitaciones y recomendaciones.

La ausencia de datos se diferenciará de una operación normal.

El chat utilizará las mismas herramientas de consulta y evidencia
que los reportes. Cada respuesta deberá respetar el acceso de
la empresa y del usuario.

La trazabilidad incluirá período consultado, evidencias utilizadas,
modelo y versión de instrucciones.

## 11. Procesos de trabajo

La ingesta extensa, el análisis y los reportes se ejecutarán fuera
del ciclo de una petición HTTP.

Inicialmente se utilizarán comandos Python invocados por un
programador externo, como cron o el Programador de tareas de Windows.

PostgreSQL conservará el estado de las tareas y sus errores.
Se controlarán concurrencia, reintentos y ejecuciones duplicadas.

No se incorporarán inicialmente Redis ni Celery.

## 12. Seguridad y operación

- Secretos en variables de entorno; nunca en Git.
- Credenciales de fuentes separadas de su configuración pública.
- Autorización por empresa y rol.
- Validación de archivos, tamaños y rutas.
- Acceso de consulta para las herramientas de análisis.
- Logs de aplicación sin credenciales ni datos sensibles innecesarios.
- Registro de errores y auditoría de operaciones relevantes.
- Políticas configurables de retención y eliminación.
- Copias de seguridad de PostgreSQL y archivos, con prueba de restauración.

El acceso multiempresa con datos reales requerirá autenticación
y autorización implementadas.

## 13. Decisiones iniciales

- Proyecto y base de datos independientes de la POC.
- Monolito modular.
- Identificadores numéricos.
- Tablas compartidas con aislamiento por company_id.
- Originales en archivos; datos consultables en PostgreSQL.
- Sin scenario ni run como entidades de negocio.
- Lotes de ingesta, ejecuciones de análisis y reportes trazables.
- Sin búsqueda vectorial en la primera versión.
- Sin acciones automáticas de remediación.

## 14. Primera entrega

- Aplicación FastAPI operativa.
- PostgreSQL y migraciones configurados.
- Registro de empresas y fuentes.
- Carga de archivos WebLogic.
- Consulta de datos normalizados.
- Pruebas de aislamiento entre empresas y de reingesta sin duplicados.

La detección, los agentes, los reportes programados y el chat
se incorporarán en entregas posteriores.