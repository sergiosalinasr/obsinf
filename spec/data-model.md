# OBSINF — Modelo de datos

Estado: definición inicial
Fecha: 2026-10-19
Motor: PostgreSQL

## 1. Objetivo

Definir las entidades de OBSINF para administrar empresas,
integrar información de infraestructura y sustentar análisis,
reportes y consultas conversacionales con evidencias.

La base de datos será independiente de observability-ai-poc.

No se utilizarán scenario ni run como entidades de negocio.
La trazabilidad operativa se resolverá mediante lotes de ingesta,
ejecuciones de análisis y reportes.

## 2. Convenciones

- Tablas y columnas en inglés, con snake_case.
- Claves primarias: BIGINT GENERATED ALWAYS AS IDENTITY.
- Referencias: BIGINT.
- Fechas: TIMESTAMPTZ.
- Instantes normalizados a UTC.
- Zona horaria de empresa mediante identificador IANA,
  por ejemplo America/Santiago.
- Valores de métricas: DOUBLE PRECISION.
- Configuraciones y atributos variables: JSONB.
- Campos obligatorios: NOT NULL.
- created_at: fecha de creación, con valor predeterminado now().
- updated_at: fecha de última modificación, mantenida por la aplicación.
- Estados iniciales mediante TEXT y restricciones CHECK.
- Los campos JSONB no reemplazarán relaciones ni campos
  necesarios para consultas frecuentes.

Las tablas pertenecientes a una empresa tendrán company_id obligatorio.

## 3. Entidades y etapas

| Entidad | Tabla | Etapa |
|---|---|---|
| Empresa | companies | Primera entrega |
| Tecnología | technologies | Primera entrega |
| Fuente | sources | Primera entrega |
| Lote de ingesta | ingestion_batches | Primera entrega |
| Archivo recibido | ingestion_files | Primera entrega |
| Error de ingesta | ingestion_errors | Primera entrega |
| Métrica | metrics_normalized | Primera entrega |
| Evento o log | events_normalized | Primera entrega |
| Ejecución de análisis | analysis_executions | Detección inicial |
| Hallazgo | findings | Posterior |
| Evidencia de hallazgo | finding_evidence | Posterior |
| Configuración de reporte | report_schedules | Posterior |
| Reporte | reports | Posterior |
| Hallazgo incluido en reporte | report_findings | Posterior |
| Conversación | conversations | Posterior |
| Mensaje | conversation_messages | Posterior |
| Evidencia de mensaje | message_evidence | Posterior |
| Membresía de usuario | company_memberships | Antes del acceso multiusuario |
| Perfil de normalidad | normality_profiles | Detección inicial |
| Regla de normalidad | normality_rules | Detección inicial |
| Evidencia determinista | evidence | Detección inicial |
| Métrica de evidencia | evidence_metrics | Detección inicial |
| Dependencia entre recursos | resource_dependencies | Análisis entre tecnologías |
| Correlación entre hallazgos | correlations | Análisis entre tecnologías |

Las entidades posteriores constituyen el diseño objetivo.
Sus migraciones se crearán cuando se implemente cada funcionalidad.

## 4. Empresas

### companies

Representa una empresa cuyos datos se administran en OBSINF.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| code | TEXT | Único, obligatorio e inmutable |
| name | TEXT | Obligatorio |
| timezone | TEXT | Obligatorio; inicialmente America/Santiago |
| is_active | BOOLEAN | Obligatorio; default true |
| created_at | TIMESTAMPTZ | Obligatorio |
| updated_at | TIMESTAMPTZ | Obligatorio |

El código se normalizará a mayúsculas y no contendrá espacios.
La aplicación validará que timezone sea un identificador IANA válido.

Desactivar una empresa impedirá nuevas ingestas y tareas programadas.
No eliminará sus datos históricos.

## 5. Tecnologías

### technologies

Catálogo global de tecnologías reconocidas por OBSINF.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| code | TEXT | Único y obligatorio |
| name | TEXT | Obligatorio |
| description | TEXT | Opcional |
| is_active | BOOLEAN | Obligatorio; default true |
| created_at | TIMESTAMPTZ | Obligatorio |
| updated_at | TIMESTAMPTZ | Obligatorio |

Ejemplos: weblogic, oracle, kubernetes, postgres, zabbix.

Una entrada en este catálogo no implica que exista un adaptador
implementado. La primera entrega habilitará WebLogic.

Esta tabla no pertenece a una empresa.

## 6. Fuentes

### sources

Representa una instancia de origen dentro de una empresa.

Ejemplos:
- WebLogic del ERP de producción.
- Cluster Kubernetes de ventas.
- Zabbix corporativo.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| technology_id | BIGINT | FK technologies |
| code | TEXT | Obligatorio; único por empresa |
| name | TEXT | Obligatorio |
| environment | TEXT | Obligatorio; default unspecified |
| ingestion_method | TEXT | file, api o collector |
| source_timezone | TEXT | Obligatorio |
| configuration | JSONB | Obligatorio; default {} |
| secret_ref | TEXT | Referencia opcional a un secreto externo |
| is_active | BOOLEAN | Obligatorio; default true |
| created_at | TIMESTAMPTZ | Obligatorio |
| updated_at | TIMESTAMPTZ | Obligatorio |

Restricciones:
- UNIQUE(company_id, code).
- UNIQUE(company_id, id).

configuration contendrá opciones no sensibles del adaptador.
No almacenará contraseñas, tokens ni claves privadas.

source_timezone permitirá interpretar fechas sin zona horaria.
La ingesta registrará cuándo fue necesario aplicar esta suposición.

Una fuente puede producir registros de varios recursos:
servidores, pods, bases de datos u otros componentes.

## 7. Ingesta

### ingestion_batches

Representa una solicitud de carga, que puede contener varios archivos.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| source_id | BIGINT | Fuente de la misma empresa |
| idempotency_key | TEXT | Obligatorio |
| status | TEXT | pending, processing, completed, partial o failed |
| parser_version | TEXT | Opcional hasta iniciar el procesamiento |
| requested_by | TEXT | Identidad autenticada o cuenta de servicio |
| received_at | TIMESTAMPTZ | Obligatorio |
| started_at | TIMESTAMPTZ | Opcional |
| finished_at | TIMESTAMPTZ | Opcional |
| records_read | BIGINT | Obligatorio; default 0 |
| records_accepted | BIGINT | Obligatorio; default 0 |
| records_rejected | BIGINT | Obligatorio; default 0 |
| records_duplicate | BIGINT | Obligatorio; default 0 |
| error_summary | TEXT | Opcional |
| request_fingerprint | TEXT | Obligatorio; SHA-256 del manifiesto normalizado y hashes de archivos |
| request_manifest | JSONB | Obligatorio; manifiesto normalizado de los archivos y formatos |
| processing_token | TEXT | Token de propiedad del procesamiento; opcional mientras no se procese |
| heartbeat_at | TIMESTAMPTZ | Última señal de actividad del proceso; opcional |
| attempt_count | INTEGER | Obligatorio; default 0; no negativo |

Restricciones:
- UNIQUE(company_id, source_id, idempotency_key).
- UNIQUE(company_id, id).
- Contadores no negativos.

Una repetición de la misma solicitud devolverá el lote existente.
Un reintento del procesamiento reutilizará el lote y aplicará
controles de duplicados sobre sus observaciones.

completed indica procesamiento sin registros rechazados.
partial indica que se aceptaron registros y se rechazaron otros.
failed indica que la carga no pudo completarse satisfactoriamente.

Los contadores reflejarán el resultado consolidado del lote,
sin acumularlos nuevamente en cada reintento.

### Idempotencia de la solicitud

idempotency_key identifica una solicitud dentro de una empresa
y una fuente.

request_fingerprint permite comprobar si una repetición contiene
los mismos archivos y parámetros.

Reglas:
- Misma clave y misma huella: devolver el lote existente.
- Misma clave y distinta huella: rechazar por conflicto.
- La huella se calculará usando una representación canónica
  del manifiesto y los hashes de los archivos en su orden declarado.
- El manifiesto incluirá posición, nombre original y formato.
- El manifiesto normalizado se conservará en request_manifest.

### Control del procesamiento

El reclamo de un lote será atómico.

Al iniciar cada intento:
- Se generará un nuevo processing_token.
- Se incrementará attempt_count.
- Se actualizará heartbeat_at.
- Se establecerá status = processing.

Toda escritura del procesador deberá comprobar que mantiene
el token vigente y que el lote continúa en estado processing.

La validación de propiedad y la escritura se realizarán dentro
de la misma transacción, bloqueando el registro del lote cuando
sea necesario para impedir carreras con la recuperación.

Un proceso anterior no podrá seguir escribiendo después
de que su token haya sido invalidado.

### Recuperación

Un comando explícito podrá recuperar un lote processing
cuyo heartbeat_at haya vencido según la configuración.

La recuperación:
- Bloqueará y volverá a comprobar el estado del lote.
- Invalidará processing_token.
- Devolverá el lote a pending.
- Conservará las observaciones ya incorporadas.
- Registrará el motivo en el logging de aplicación.

El siguiente intento aplicará los controles de deduplicación.

started_at representará el inicio del intento más reciente.
finished_at se limpiará al reintentar y se completará al finalizar.

Los contadores se recalcularán durante el nuevo intento.
Los errores de ingesta del intento anterior se reemplazarán
de forma controlada, evitando multiplicarlos por cada reintento.

### ingestion_files

Registra los archivos asociados a un lote.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| batch_id | BIGINT | Lote de la misma empresa |
| original_filename | TEXT | Obligatorio |
| storage_key | TEXT | Obligatorio |
| sha256 | TEXT | Obligatorio |
| size_bytes | BIGINT | Obligatorio; no negativo |
| content_type | TEXT | Opcional |
| status | TEXT | received, processing, processed, partial o rejected |
| received_at | TIMESTAMPTZ | Obligatorio |
| processed_at | TIMESTAMPTZ | Opcional |
| error_summary | TEXT | Opcional |

Restricciones:
- UNIQUE(company_id, id).
- UNIQUE(company_id, storage_key).

storage_key será una ruta relativa a OBSINF_DATA_DIR.
La aplicación generará el nombre físico para evitar colisiones.

Ejemplo:
companies/3/raw/7/2026/10/19/42_weblogic.log

El hash permite reconocer contenido idéntico.
No será único globalmente: un mismo archivo puede recibirse
en distintos lotes o pertenecer a empresas diferentes.

### ingestion_errors

Registra errores de validación o interpretación.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| batch_id | BIGINT | Lote de la misma empresa |
| file_id | BIGINT | Archivo opcional del mismo lote |
| record_locator | TEXT | Línea, posición o identificador de registro |
| error_code | TEXT | Obligatorio |
| message | TEXT | Obligatorio |
| created_at | TIMESTAMPTZ | Obligatorio |

Los mensajes no expondrán secretos ni copiarán indiscriminadamente
el contenido de registros sensibles.

## 8. Observaciones normalizadas

### Capas de almacenamiento

- Raw: archivos originales conservados sin modificar en el
  almacenamiento de archivos. ingestion_files registra su ubicación,
  hash y metadatos.
- Normalizada: tablas metrics_normalized y events_normalized,
  con datos interpretados, validados y vinculados a su origen.

No se crearán metrics_raw ni events_raw en esta etapa.
Los originales permitirán reprocesar la información cuando
se modifiquen los adaptadores.

Se separarán métricas de eventos y logs porque sus estructuras
y consultas son diferentes.

### metrics_normalized

Cada fila representa el valor de una métrica para un recurso
y un instante.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| source_id | BIGINT | Fuente de la misma empresa |
| batch_id | BIGINT | Lote de la misma empresa y fuente |
| file_id | BIGINT | Archivo opcional del mismo lote |
| record_locator | TEXT | Referencia al registro original |
| resource_key | TEXT | Identificador del recurso dentro de la fuente |
| metric_name | TEXT | Nombre normalizado |
| value | DOUBLE PRECISION | Obligatorio y finito |
| unit | TEXT | Unidad normalizada |
| observed_at | TIMESTAMPTZ | Momento de la medición |
| received_at | TIMESTAMPTZ | Momento de incorporación |
| attributes | JSONB | Obligatorio; default {} |
| dedup_key | TEXT | Obligatorio |

Restricciones:
- UNIQUE(company_id, id).
- UNIQUE(company_id, source_id, dedup_key).

Ejemplos de metric_name:
- cpu_usage_percent
- memory_usage_percent
- jdbc_active_connections
- http_response_time_ms

Los nombres, unidades y conversiones se definirán en el contrato
de cada adaptador.

attributes conservará dimensiones adicionales relevantes.
No se mezclarán mediciones de dimensiones distintas al agregarlas.

### events_normalized

Almacena eventos estructurados y entradas de log.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies |
| source_id | BIGINT | Fuente de la misma empresa |
| batch_id | BIGINT | Lote de la misma empresa y fuente |
| file_id | BIGINT | Archivo opcional del mismo lote |
| record_locator | TEXT | Referencia al registro original |
| resource_key | TEXT | Identificador del recurso |
| record_type | TEXT | event o log |
| severity | TEXT | unknown, debug, info, warning, error o critical |
| original_severity | TEXT | Severidad original opcional |
| event_code | TEXT | Código original opcional |
| message | TEXT | Obligatorio |
| occurred_at | TIMESTAMPTZ | Momento del evento |
| received_at | TIMESTAMPTZ | Momento de incorporación |
| attributes | JSONB | Obligatorio; default {} |
| dedup_key | TEXT | Obligatorio |

Restricciones:
- UNIQUE(company_id, id).
- UNIQUE(company_id, source_id, dedup_key).

El adaptador documentará el mapeo de severidades.

### Reglas de normalización y duplicados

- Se conservará el instante original en attributes cuando
  sea necesario explicar una conversión de zona horaria.
- Un registro sin fecha interpretable será rechazado en la
  primera entrega; no se sustituirá silenciosamente por now().
- dedup_key será estable entre reintentos.
- Se priorizará el identificador original del proveedor.
- Si no existe, el adaptador definirá una huella considerando
  recurso, instante, contenido, dimensiones y posición disponible.
- No se deduplicarán eventos solamente por mensaje y fecha:
  podrían ser repeticiones legítimas.
- Las limitaciones de deduplicación se documentarán por adaptador.

## 9. Ejecuciones de análisis

### analysis_executions

Registra el procesamiento de un período para una empresa.

Campos principales:
- id, company_id.
- period_start, period_end: TIMESTAMPTZ.
- data_cutoff_at: límite de recepción de datos considerados.
- status: pending, processing, completed o failed.
- trigger_type: manual o scheduled.
- started_at, finished_at.
- detector_version.
- agent_version, model_name: opcionales.
- parameters: JSONB.
- coverage: JSONB.
- error_summary: opcional.
- created_at.

Reglas:
- period_start < period_end.
- Los intervalos serán [period_start, period_end).
- La selección considerará el instante del evento o medición
  y received_at <= data_cutoff_at.
- La cobertura distinguirá fuentes con datos, sin datos o con errores.

Esta entidad registra trabajo operativo; no representa un escenario.

## 10. Hallazgos y evidencias

### findings

Representa un comportamiento relevante detectado en un análisis.

Campos principales:
- id, company_id, analysis_execution_id.
- title, description.
- category.
- severity: info, warning, error o critical.
- assessment_type: observed o hypothesis.
- period_start, period_end.
- detection_method: rule, statistical, agent o combined.
- detector_code.
- created_at.

La severidad del hallazgo es independiente de la severidad
de un log individual.

Los hallazgos de una ejecución completada serán inmutables.
Un nuevo análisis podrá generar nuevos hallazgos.

El seguimiento de incidentes y su ciclo de resolución queda
fuera del modelo inicial.

### finding_evidence

Relaciona hallazgos con observaciones que los sustentan.

Campos:
- id, company_id, finding_id.
- metric_id: opcional.
- event_id: opcional.
- explanation: texto que explica la relación.
- created_at.

Exactamente una de las referencias metric_id o
event_id deberá estar informada.

Todas las referencias pertenecerán a la misma empresa.

Los cálculos agregados se identificarán mediante la versión
del detector y los parámetros de la ejecución. Las observaciones
referenciadas permitirán verificar sus resultados.

## 11. Reportes

### report_schedules

Configuración de generación por empresa.

Campos:
- id, company_id.
- name.
- local_time: TIME WITHOUT TIME ZONE.
- timezone: identificador IANA.
- lookback_hours: INTEGER positivo.
- is_active.
- created_at, updated_at.

El programador utilizará una política explícita para cambios
de horario de verano, evitando generar dos veces el mismo reporte.

### reports

Conserva el contenido generado para un período.

Campos:
- id, company_id.
- schedule_id: opcional.
- analysis_execution_id.
- scheduled_for: TIMESTAMPTZ, opcional para reportes manuales.
- period_start, period_end.
- status: pending, processing, completed o failed.
- content_markdown: opcional hasta completar.
- coverage: JSONB.
- model_name, prompt_version: opcionales.
- export_storage_key: opcional.
- created_at, completed_at.
- error_summary: opcional.

Para reportes programados:
- UNIQUE(company_id, schedule_id, scheduled_for).

El reporte conservará una copia de la cobertura y del contenido
publicado, para que su interpretación no dependa de cambios futuros.

### report_findings

Relaciona reportes y hallazgos.

Campos:
- company_id.
- report_id.
- finding_id.
- position.

Clave primaria:
- (company_id, report_id, finding_id).

## 12. Conversaciones

### conversations

Campos:
- id, company_id.
- owner_subject: identidad del usuario autenticado.
- title: opcional.
- adk_session_id: opcional, para vincular la sesión del agente.
- created_at, updated_at.

Las sesiones ADK deberán aislarse por empresa y usuario.
Su almacenamiento interno no sustituirá el historial funcional
y las evidencias registradas por OBSINF.

### conversation_messages

Campos:
- id, company_id, conversation_id.
- role: user o assistant.
- status: pending, completed o failed.
- content.
- period_start, period_end: opcionales.
- data_cutoff_at: opcional.
- model_name, prompt_version: opcionales.
- created_at.
- error_summary: opcional.

Los mensajes de sistema y las instrucciones internas no se
expondrán como mensajes de usuario.

### message_evidence

Campos:
- id, company_id, message_id.
- metric_id: opcional.
- event_id: opcional.
- finding_id: opcional.
- report_id: opcional.
- explanation.

Exactamente una referencia de evidencia deberá estar informada.
Todas las referencias pertenecerán a la misma empresa.

## 13. Acceso de usuarios

### company_memberships

Relaciona identidades autenticadas con empresas.

Campos:
- id, company_id.
- identity_issuer.
- identity_subject.
- role: admin, operator o viewer.
- is_active.
- created_at, updated_at.

Restricción:
- UNIQUE(company_id, identity_issuer, identity_subject).

La combinación issuer y subject identifica al usuario.
No se utilizará el correo como identificador estable.

Los permisos concretos de cada rol se definirán en la
especificación de autenticación y autorización.

El desarrollo inicial podrá trabajar con una empresa explícita
en un entorno local restringido. El acceso multiusuario y la
exposición de datos reales requerirán autorización implementada.

## 14. Integridad multiempresa

Un filtro company_id en la aplicación no será la única protección.

Las tablas de empresa expondrán UNIQUE(company_id, id) para
permitir claves foráneas compuestas.

Ejemplo:

FOREIGN KEY (company_id, source_id)
REFERENCES sources (company_id, id)

Cuando una entidad repita fuente, lote o archivo, las restricciones
también deberán garantizar que correspondan al mismo origen.

Se agregarán las claves únicas compuestas necesarias para verificar:
- Que el lote pertenece a la fuente.
- Que el archivo pertenece al lote.
- Que una observación no referencia un archivo de otro lote.
- Que las evidencias pertenecen a la empresa del hallazgo o mensaje.

La autorización también se aplicará en servicios, tareas
y herramientas de agentes.

Se evaluará Row-Level Security antes de la exposición multiempresa
a producción como protección adicional.

## 15. Índices iniciales

Además de claves primarias y restricciones únicas:

- sources(company_id, technology_id).
- ingestion_batches(company_id, received_at DESC).
- ingestion_files(company_id, batch_id).
- ingestion_errors(company_id, batch_id).
- metrics_normalized(company_id, source_id, metric_name, observed_at).
- metrics_normalized(company_id, observed_at).
- events_normalized(company_id, source_id, occurred_at).
- events_normalized(company_id, occurred_at).
- findings(company_id, period_start).
- reports(company_id, created_at DESC).
- conversation_messages(company_id, conversation_id, created_at, id).

Los índices adicionales se justificarán mediante consultas reales.
No se indexarán indiscriminadamente todos los campos JSONB.

El particionamiento temporal se evaluará según volumen y retención;
no forma parte de la primera entrega.

## 16. Retención y eliminación

- No se utilizará borrado en cascada desde companies.
- Empresas y fuentes se desactivarán para conservar históricos.
- La eliminación física será una operación controlada.
- Las evidencias referenciadas por reportes o conversaciones
  se conservarán mientras se requiera verificar esos resultados.
- Una política futura de depuración deberá preservar las evidencias
  necesarias o señalar explícitamente su vencimiento.
- Archivos y metadatos se eliminarán de forma coordinada.
- Las copias de seguridad tendrán su propia política de retención.

## 17. Primera migración

La primera entrega creará:

1. companies.
2. technologies.
3. sources.
4. ingestion_batches.
5. ingestion_files.
6. ingestion_errors.
7. metrics_normalized.
8. events_normalized.

Se incorporará WebLogic al catálogo de tecnologías.
No se crearán empresas reales mediante datos de prueba.

## 18. Validaciones de aceptación

- Consultar fuentes con company_id numérico.
- Permitir el mismo código de fuente en empresas distintas.
- Rechazar códigos de fuente duplicados dentro de una empresa.
- Impedir relaciones entre empresas distintas.
- Impedir referencias inconsistentes entre fuente, lote y archivo.
- Conservar el original y localizar el registro de origen.
- Repetir una solicitud sin duplicar el lote.
- Reintentar una ingesta sin duplicar observaciones.
- Conservar eventos repetidos legítimos.
- Registrar errores y cargas parcialmente aceptadas.
- Normalizar fechas y unidades según el contrato del adaptador.
- Rechazar una clave de idempotencia reutilizada con contenido distinto.
- Impedir que dos procesos reclamen simultáneamente el mismo lote.
- Recuperar explícitamente lotes con actividad vencida.
- Impedir escrituras de un procesador cuyo token fue invalidado.
- Reintentar sin multiplicar observaciones, errores ni contadores.

## 19. Normalidad operativa configurada

La normalidad define los valores esperados de una métrica para
una empresa, fuente, recurso y conjunto de dimensiones.

Los perfiles iniciales serán CONFIGURED: sus límites se establecen
explícitamente. No representan una normalidad aprendida de históricos.

Los valores reutilizados de la POC serán configuración de demostración,
no umbrales universales de las tecnologías.

### normality_profiles

Identifica una versión de un perfil de normalidad de una empresa.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | FK companies; obligatorio |
| code | TEXT | Obligatorio |
| version | TEXT | Obligatorio |
| name | TEXT | Obligatorio |
| description | TEXT | Opcional |
| profile_type | TEXT | Obligatorio; CONFIGURED |
| status | TEXT | draft, active o retired; default draft |
| created_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |
| updated_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |

Restricciones:
- UNIQUE(company_id, code, version).
- UNIQUE(company_id, id).
- code, version y name no pueden estar vacíos.
- profile_type solo admite CONFIGURED en esta etapa.
- Solo puede existir una versión active por empresa y código.

La última regla se implementará mediante un índice único parcial:

UNIQUE(company_id, code) WHERE status = 'active'

Ciclo de vida:
- draft: permite editar el perfil y sus reglas.
- active: versión publicada, disponible para análisis.
- retired: versión histórica, excluida de nuevos análisis.

Transiciones permitidas:
- draft → active.
- active → retired.

Una versión publicada no se modifica ni se elimina.
Los cambios requieren crear otra versión draft.

La activación de una nueva versión y el retiro de la anterior
serán una operación transaccional.

Las transiciones y la inmutabilidad se controlarán en los servicios.
Las restricciones de unicidad y los valores de estado se verificarán
también en PostgreSQL.

### normality_rules

Define una regla numérica dentro de un perfil.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | Obligatorio |
| profile_id | BIGINT | Perfil de la misma empresa |
| source_id | BIGINT | Fuente de la misma empresa |
| resource_key | TEXT | Recurso exacto; obligatorio |
| metric_name | TEXT | Nombre normalizado; obligatorio |
| unit | TEXT | Unidad normalizada; obligatoria |
| dimensions | JSONB | Objeto obligatorio; default {} |
| series_key | TEXT | Representación canónica de dimensions; obligatoria |
| lower_threshold | DOUBLE PRECISION | Opcional |
| upper_threshold | DOUBLE PRECISION | Opcional |
| min_samples | INTEGER | Obligatorio; default 1 |
| max_gap_seconds | DOUBLE PRECISION | Obligatorio; sin valor predeterminado |
| created_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |
| updated_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |

Restricciones de identidad y pertenencia:
- UNIQUE(company_id, id).
- UNIQUE(company_id, profile_id, source_id, resource_key,
  metric_name, unit, series_key).
- FOREIGN KEY(company_id, profile_id)
  REFERENCES normality_profiles(company_id, id).
- FOREIGN KEY(company_id, source_id)
  REFERENCES sources(company_id, id).

Restricciones de valores:
- resource_key, metric_name, unit y series_key no pueden estar vacíos.
- dimensions debe ser un objeto JSON.
- Debe existir al menos un límite.
- Los límites informados deben ser finitos: no NaN ni infinitos.
- Si ambos límites existen, lower_threshold <= upper_threshold.
- min_samples >= 1.
- max_gap_seconds debe ser positivo y finito.

### Semántica de las reglas

Los límites son inclusivos:
- value < lower_threshold: desviación inferior.
- value > upper_threshold: desviación superior.
- Un valor igual a un límite está dentro del rango permitido.

Un valor esperado exacto se representa con ambos límites iguales.

Ejemplo:
- lower_threshold = 0.
- upper_threshold = 0.
- Cualquier valor distinto de cero constituye una desviación.

min_samples indica cuántas muestras desviadas consecutivas
se requieren para emitir evidencia.

max_gap_seconds establece la separación temporal máxima permitida
entre muestras del mismo grupo.

Un hueco mayor interrumpe el grupo; no demuestra recuperación
ni continuidad de la condición.

La duración informada corresponde al tiempo entre la primera
y la última muestra desviada del grupo.

### Identidad de la serie y dimensiones

Una serie se identifica mediante:
- company_id.
- source_id.
- resource_key.
- metric_name.
- unit.
- dimensions.

dimensions contiene únicamente las dimensiones que identifican
la serie, según el contrato del adaptador.

No se utilizarán automáticamente todos los attributes de una
observación: pueden incluir metadatos que no identifican la serie.

series_key será el JSON canónico de dimensions:
- Claves ordenadas.
- Sin espacios de formato.
- Sin valores numéricos no finitos.
- Generado por el servicio, no aceptado como dato independiente.

Ejemplo:
- dimensions = {}.
- series_key = "{}".

El servicio garantizará que dimensions y series_key sean coherentes.

La primera implementación admite coincidencia exacta de recurso
y dimensiones. No admite comodines ni herencia de reglas.

Los adaptadores actuales no han definido dimensiones de serie;
inicialmente se utilizará {} para sus observaciones.

### Selección para análisis

Un análisis seleccionará explícitamente un perfil y registrará:
- profile_id.
- Código y versión.
- IDs de las reglas aplicadas.
- Versión del detector.

Solo se iniciarán análisis nuevos con perfiles active.

Si se solicita un análisis sin configuración aplicable,
se informará que no existe normalidad configurada.

Si existe una regla pero no hay mediciones compatibles,
se informará ausencia de datos para esa regla.

Ninguno de esos casos se interpretará como operación normal.

El detector utilizará métricas de cualquier lote que cumplan
empresa, fuente, recurso, métrica, unidad, dimensiones y período.

La normalidad no se seleccionará por batch_id.

### Índices

Además de las restricciones únicas:
- normality_profiles(company_id, status).
- normality_rules(company_id, source_id, metric_name).

### Trazabilidad y conservación

Las futuras ejecuciones de análisis conservarán la referencia
al perfil y a las reglas efectivamente utilizadas.

No se permitirá borrar perfiles o reglas referenciados por análisis.
No se configurará borrado en cascada desde empresas o fuentes.

Los resultados del detector conservarán los IDs de las mediciones
que sustentan cada desviación.

### Validaciones de aceptación

- Permitir el mismo código y versión de perfil en empresas distintas.
- Rechazar código y versión duplicados dentro de una empresa.
- Impedir dos versiones active del mismo código y empresa.
- Impedir reglas vinculadas a perfiles o fuentes de otra empresa.
- Rechazar reglas duplicadas dentro de un perfil.
- Rechazar reglas sin límites.
- Rechazar límites invertidos, NaN o infinitos.
- Permitir un valor esperado exacto.
- Rechazar min_samples menor que 1.
- Rechazar max_gap_seconds no positivo o no finito.
- Mantener coherencia entre dimensions y series_key.
- Impedir modificaciones de perfiles y reglas publicados.
- Diferenciar ausencia de configuración, ausencia de datos
  y ausencia de desviaciones.

## 20. Dependencias entre recursos

### resource_dependencies

Registra una relación configurada y dirigida entre un recurso
consumidor y un recurso proveedor de la misma empresa.

La relación aporta contexto de arquitectura. No demuestra causalidad,
impacto operativo ni propagación de una anomalía.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | Obligatorio |
| consumer_source_id | BIGINT | Fuente consumidora de la misma empresa |
| consumer_resource_key | TEXT | Identificador exacto del recurso consumidor |
| provider_source_id | BIGINT | Fuente proveedora de la misma empresa |
| provider_resource_key | TEXT | Identificador exacto del recurso proveedor |
| dependency_type | TEXT | uses_database_service en esta etapa |
| description | TEXT | Obligatorio; explica la relación y su procedencia |
| configured_by | TEXT | Obligatorio; identidad que registra la configuración |
| is_active | BOOLEAN | Obligatorio; default true |
| created_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |
| updated_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |

Restricciones:

- UNIQUE(company_id, id).
- UNIQUE(company_id, consumer_source_id, consumer_resource_key,
  provider_source_id, provider_resource_key, dependency_type).
- Ambas fuentes deben pertenecer a company_id mediante claves
  foráneas compuestas hacia sources(company_id, id).
- Las claves de recurso, description y configured_by no pueden
  estar vacías.
- El consumidor y proveedor no pueden ser el mismo recurso
  de la misma fuente.
- No se configura borrado en cascada.

Índices:

- La restricción única permite buscar por empresa y consumidor.
- Índice adicional por empresa, fuente y recurso proveedor.

Alcance inicial:

- La configuración es explícita; no se infiere por nombres,
  cercanía temporal ni respuestas del LLM.
- Los resource_key coinciden exactamente con los identificadores
  utilizados por los adaptadores.
- No existe todavía un catálogo independiente de recursos.
  Por ello, PostgreSQL garantiza la pertenencia de las fuentes,
  pero no la existencia de cada recurso en las observaciones.
- La relación puede configurarse antes de recibir observaciones.
- configured_by se obtendrá del contexto autenticado; durante
  el desarrollo local se utilizará local-dev.
- Una relación desactivada se conserva y puede reactivarse.
- Esta etapa representa configuración vigente; no incluye
  intervalos históricos de validez ni detección de ciclos.
- No se utilizará la fecha de creación como fecha de inicio
  real de la dependencia.

Trazabilidad del análisis conjunto:

Cuando se implemente la correlación, cada resultado conservará
una copia de la dependencia utilizada y su procedencia.
Modificar la configuración no reinterpretará resultados guardados.

Para períodos anteriores a su registro, la dependencia solo
se utilizará como configuración declarada para ese análisis,
sin afirmar que su vigencia histórica fue comprobada.

Ejemplo de demostración:

- Empresa: 1.
- Consumidor: fuente 2, recurso ManagedServer1.
- Proveedor: fuente 4, recurso ORCLPDB1/ERP_SERVICE.
- Tipo: uses_database_service.
- Descripción: relación configurada para la demostración;
  no verificada contra una configuración real de datasource.

Esta declaración no permite atribuir las métricas JDBC
del servidor a un datasource específico ni concluir que
el bloqueo Oracle causó las desviaciones WebLogic.

## 21. Coordinador y correlaciones

### correlations

Conserva la interpretación conjunta de dos hallazgos vinculados
por una dependencia configurada entre recursos.

La primera implementación admite WebLogic como consumidor
y Oracle como proveedor de un servicio de base de datos.

Una correlación no modifica los hallazgos originales.

| Campo | Tipo | Regla |
|---|---|---|
| id | BIGINT IDENTITY | PK |
| company_id | BIGINT | Obligatorio |
| dependency_id | BIGINT | Dependencia de la misma empresa |
| consumer_finding_id | BIGINT | Hallazgo consumidor de la misma empresa |
| provider_finding_id | BIGINT | Hallazgo proveedor de la misma empresa |
| proposal | JSONB | Respuesta validada del coordinador |
| context_snapshot | JSONB | Copia del contexto enviado al coordinador |
| agent_name | TEXT | Obligatorio |
| model_name | TEXT | Obligatorio |
| prompt_sha256 | TEXT | SHA-256 de la instrucción exacta |
| context_sha256 | TEXT | SHA-256 del contexto canónico |
| request_sha256 | TEXT | SHA-256 de la identidad de interpretación |
| created_at | TIMESTAMPTZ | Obligatorio; reloj PostgreSQL |

Restricciones:

- UNIQUE(company_id, id).
- UNIQUE(company_id, request_sha256).
- Claves foráneas compuestas hacia la dependencia y ambos hallazgos.
- Los dos hallazgos deben ser diferentes.
- proposal y context_snapshot deben ser objetos JSON.
- Agente y modelo no pueden estar vacíos.
- Los tres hashes deben tener 64 caracteres.
- No se configura borrado en cascada.

El servicio valida adicionalmente:

- Correspondencia entre los hallazgos y los extremos de la dependencia.
- Pertenencia de evidencias y eventos al contexto autorizado.
- Estado y períodos de las ejecuciones.
- Coincidencias entre ventanas de evidencias individuales.
- Igualdad del contexto seleccionado antes y después de llamar al modelo.

### Contrato de la propuesta

proposal conserva:

- dependency_id.
- finding_ids: los dos hallazgos seleccionados.
- evidence_ids: todas sus evidencias seleccionadas.
- event_ids: eventos citados por el coordinador.
- assessment: TEMPORAL_COINCIDENCE o NO_TEMPORAL_COINCIDENCE.
- causality: NOT_ESTABLISHED en esta etapa.
- confidence: estimación declarada, no probabilidad calibrada.
- summary: síntesis interpretativa.
- evidence_overlaps: parejas de evidencias temporalmente coincidentes.
- limitations: limitaciones de la interpretación.

Los intervalos se comparan entre evidencias individuales.
La ventana completa de un hallazgo no prueba continuidad.

Una coincidencia temporal y una dependencia configurada
no demuestran causalidad.

### Contexto conservado

context_snapshot contiene la dependencia, fuentes, hallazgos,
evidencias, contexto original de eventos, ejecuciones,
cobertura y cortes de recepción utilizados.

Cada ejecución conserva su propio data_cutoff_at.
No se asigna artificialmente un corte común.

La copia conserva el contexto histórico: cambios posteriores
en la configuración no actualizan las correlaciones guardadas.

### Identidad y duplicados

request_sha256 identifica la combinación de:

- Hash del contexto canónico.
- Hash del prompt exacto.
- Agente.
- Modelo.

No se permite guardar otra respuesta para la misma combinación.
Un contexto, prompt o modelo diferente permite otra interpretación.

Los hashes permiten comprobar identidad; no son firmas digitales
ni garantizan que la interpretación sea correcta.

### Consultas

- GET /api/v1/companies/{company_id}/correlations.
- GET /api/v1/companies/{company_id}/correlations/{correlation_id}.

El listado permite filtrar por dependency_id y pagina por ID ascendente.
El detalle incluye context_snapshot.

Las consultas siempre se limitan a la empresa solicitada.
Un ID perteneciente a otra empresa se presenta como no encontrado.

Las correlaciones se conservan como resultados históricos.
Estas APIs no permiten editarlas ni eliminarlas.

Índice adicional:

- correlations(company_id, dependency_id).