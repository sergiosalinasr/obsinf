# 001 — Empresas, fuentes e ingesta inicial

Estado: especificación inicial
Fecha: 2026-10-19

## 1. Objetivo

Permitir registrar empresas y fuentes, cargar archivos de WebLogic
y consultar métricas y eventos normalizados, conservando los
originales y la trazabilidad de cada carga.

Esta funcionalidad constituye la primera entrega vertical de OBSINF.

Referencias:
- spec/architecture.md
- spec/data-model.md

## 2. Alcance

Incluye:
- Registro, consulta y actualización de empresas.
- Registro, consulta y actualización de fuentes.
- Consulta del catálogo de tecnologías.
- Carga de archivos de una fuente WebLogic.
- Procesamiento mediante un comando Python independiente.
- Consulta del estado y resultado de cada carga.
- Consulta paginada de métricas y eventos.
- Conservación y descarga autorizada de archivos originales.
- Registro de errores de ingesta.
- Controles de aislamiento e idempotencia.

No incluye en esta entrega:
- Interfaz gráfica.
- Agentes ADK y llamadas a modelos.
- Detección de anomalías o correlación.
- Reportes programados y chat.
- Conexión directa a servidores WebLogic.
- Ingesta mediante APIs o recolectores.
- Eliminación física de datos.

## 3. Usuarios y acceso

Roles previstos:
- admin: administra empresas, fuentes e ingestas.
- operator: administra fuentes y realiza ingestas de sus empresas.
- viewer: consulta información de sus empresas.

La creación de empresas se reservará a un administrador de plataforma.
Una membresía admin de empresa no otorga ese permiso global.

### Desarrollo local

Se permitirá un modo local explícito para probar la funcionalidad
sin proveedor de identidad.

Condiciones:
- Activación mediante configuración.
- API vinculada a 127.0.0.1.
- Uso exclusivo de datos sintéticos.
- No se considerará una implementación de autenticación.
- La aplicación rechazará iniciar este modo en un entorno
  configurado como producción.

La exposición a usuarios o el uso de datos reales requerirá
autenticación y autorización implementadas.

## 4. Historias de usuario

### HU-01 — Registrar empresa

Como administrador de plataforma,
quiero registrar una empresa,
para organizar sus fuentes y datos de manera independiente.

Criterios:
- Se requiere code, name y timezone.
- code se normaliza a mayúsculas.
- code debe ser único y no contener espacios.
- timezone debe ser un identificador IANA válido.
- El sistema genera un ID numérico.
- La empresa se crea activa.
- Se devuelven su ID y los datos registrados.

### HU-02 — Administrar fuente

Como administrador u operador autorizado,
quiero registrar una fuente de una empresa,
para identificar el origen de sus observaciones.

Criterios:
- La empresa debe existir y estar activa.
- Se requiere code, name, technology_id y source_timezone.
- code debe ser único dentro de la empresa.
- Para esta entrega, ingestion_method debe ser file.
- Solo se aceptan tecnologías con adaptador habilitado.
- La primera tecnología habilitada será WebLogic.
- No se admitirán secretos en configuration.
- Una vez que tenga ingestas, no se podrá cambiar su empresa
  ni su tecnología.

### HU-03 — Cargar archivos

Como administrador u operador autorizado,
quiero cargar archivos de una fuente,
para incorporarlos a OBSINF.

Criterios:
- Empresa y fuente deben existir y estar activas.
- La fuente debe pertenecer a la empresa indicada.
- Se requiere una clave de idempotencia.
- Se admite uno o varios archivos por solicitud.
- Se validan cantidad, tamaño y formato permitido.
- Los nombres físicos los genera el sistema.
- Se conserva el nombre original como metadato.
- Se calcula SHA-256 sobre los bytes recibidos.
- Los originales se guardan antes de aceptar la carga.
- Se registra un lote en estado pending.
- La respuesta incluye el identificador y la URL de consulta.
- La solicitud no realiza el parsing completo de los archivos.

### HU-04 — Procesar una carga

Como operador,
quiero ejecutar el procesamiento de un lote pendiente,
para obtener observaciones normalizadas y conocer sus errores.

Criterios:
- El procesamiento se ejecuta fuera de la petición HTTP.
- El proceso reclama el lote de forma atómica.
- Dos procesos no pueden procesar simultáneamente el mismo lote.
- Se registra la versión del parser.
- Cada observación conserva su origen y posición disponible.
- Los registros inválidos generan errores identificables.
- Los registros válidos pueden guardarse aunque otros fallen.
- Los contadores se consolidan sin duplicarse por reintentos.
- Se registra el estado final del lote y de sus archivos.

### HU-05 — Consultar resultados

Como usuario autorizado,
quiero consultar observaciones y errores,
para verificar qué información se incorporó.

Criterios:
- Todas las consultas están acotadas a una empresa autorizada.
- Se permite filtrar por fuente y período.
- Las métricas permiten filtrar por metric_name y resource_key.
- Los eventos permiten filtrar por severity, event_code y resource_key.
- Los resultados están paginados y ordenados de forma estable.
- Cada observación muestra su lote y referencia de origen.
- Los errores permiten identificar archivo y registro afectado.

## 5. Contrato inicial del adaptador WebLogic

Se admitirán dos formatos explícitos:
- weblogic_log_v1: registros de log WebLogic.
- obsinf_metrics_jsonl_v1: métricas en JSON Lines.

El formato se indicará por archivo en la solicitud.
No se inferirá únicamente desde su extensión.

### 5.1 Logs WebLogic

La primera implementación soportará un perfil documentado de
registros cuyo encabezado tenga esta estructura:

####<timestamp> <severity> <subsystem> <host> <server>
<thread> <user> <transaction> <context> <raw_time>
<message_code> <message>

El parser deberá:
- Identificar el comienzo de cada registro.
- Agrupar líneas de continuación, como stack traces.
- Extraer fecha, severidad, servidor, código y mensaje.
- Conservar los campos adicionales en attributes.
- Registrar el rango de líneas en record_locator.
- Utilizar el servidor como resource_key.
- Conservar el texto original en el archivo recibido.
- Rechazar encabezados o fechas no interpretables.
- No descartar silenciosamente contenido previo al primer encabezado.

El perfil exacto de timestamp y sus variantes admitidas se fijará
con fixtures sintéticos antes de implementar el parser.
Se documentará en el módulo del adaptador.

No se declarará soporte universal de todos los formatos WebLogic.

### 5.2 Métricas JSONL

Este es un contrato de intercambio de OBSINF, no un formato
nativo universal de WebLogic.

Cada línea contendrá un objeto JSON independiente.

Campos:
- timestamp: fecha ISO 8601 con zona horaria.
- resource_key: identificador no vacío.
- metric_name: nombre del catálogo del adaptador.
- value: número finito.
- unit: unidad correspondiente a la métrica.
- attributes: objeto opcional.

Ejemplo:

{"timestamp":"2026-10-19T09:00:00-03:00","resource_key":"ManagedServer1","metric_name":"cpu_usage_percent","value":46.5,"unit":"percent","attributes":{}}

Catálogo inicial:

| metric_name | unit | Validación |
|---|---|---|
| cpu_usage_percent | percent | Entre 0 y 100 |
| memory_usage_percent | percent | Entre 0 y 100 |
| jdbc_active_connections | count | Entero no negativo |
| http_response_time_ms | ms | No negativo |

Las métricas desconocidas o las unidades incompatibles se rechazan.
No se aplicarán conversiones implícitas sin documentarlas.

Una línea JSON inválida no impedirá procesar las restantes.

### 5.3 Codificación

- La primera versión admitirá UTF-8, con o sin BOM.
- No se reemplazarán silenciosamente bytes inválidos.
- Un archivo con codificación no admitida será rechazado.
- No se admitirán archivos comprimidos en esta entrega.

## 6. API inicial

Prefijo: /api/v1

| Método | Ruta | Propósito |
|---|---|---|
| GET | /health/live | Verificar que la API responde |
| GET | /health/ready | Verificar acceso a BD y almacenamiento |
| POST | /companies | Registrar empresa |
| GET | /companies | Listar empresas autorizadas |
| GET | /companies/{company_id} | Consultar empresa |
| PATCH | /companies/{company_id} | Actualizar nombre, zona horaria o estado |
| GET | /technologies | Consultar catálogo y adaptadores disponibles |
| POST | /companies/{company_id}/sources | Registrar fuente |
| GET | /companies/{company_id}/sources | Listar fuentes |
| GET | /companies/{company_id}/sources/{source_id} | Consultar fuente |
| PATCH | /companies/{company_id}/sources/{source_id} | Actualizar fuente |
| POST | /companies/{company_id}/sources/{source_id}/ingestions | Recibir archivos |
| GET | /companies/{company_id}/ingestions | Listar lotes |
| GET | /companies/{company_id}/ingestions/{batch_id} | Consultar resultado |
| GET | /companies/{company_id}/ingestions/{batch_id}/errors | Consultar errores |
| GET | /companies/{company_id}/ingestions/{batch_id}/files/{file_id}/download | Descargar original |
| GET | /companies/{company_id}/metrics | Consultar métricas |
| GET | /companies/{company_id}/events | Consultar eventos |

La descarga devolverá el original como archivo adjunto.
No expondrá rutas físicas ni permitirá indicar una ruta arbitraria.

### Recepción de archivos

La solicitud usará multipart/form-data:
- files: archivos.
- manifest: JSON que asocia cada archivo con su formato.

El manifiesto identificará los archivos por su posición en files,
evitando depender de nombres originales que podrían repetirse.

Cabecera obligatoria:
- Idempotency-Key.

Respuesta inicial:
- HTTP 202.
- batch_id.
- status.
- URL para consultar el lote.

### Respuestas comunes

- 404: recurso inexistente o fuera del ámbito autorizado.
- 409: código duplicado, conflicto de estado o reutilización
  incompatible de una clave de idempotencia.
- 413: límites de carga excedidos.
- 422: campos o manifiesto inválidos.
- 503: dependencia necesaria no disponible.

Los errores tendrán un código estable y un mensaje comprensible.
No incluirán credenciales, trazas internas ni rutas del servidor.

### Consultas temporales

- from y to serán obligatorios al consultar observaciones.
- Se requerirán fechas con zona horaria.
- Se aplicará el intervalo [from, to).
- La primera versión limitará la ventana a 31 días,
  configurable.
- Los resultados devolverán fechas en UTC.

### Paginación

- limit predeterminado: 100.
- limit máximo: 1000.
- Se utilizará un cursor opaco.
- Orden de observaciones: instante e id.
- Los filtros deberán mantenerse al continuar la paginación.

## 7. Procesamiento y estados

Comandos previstos, ejecutados desde la raíz del proyecto:

python -m app.jobs.process_ingestion --company-id 3 --batch-id 42
python -m app.jobs.process_ingestion --pending --limit 10

El segundo comando procesará lotes pendientes y comprobará
empresa y fuente antes de cada ejecución.

Estados del lote:

- pending: recibido y disponible para procesamiento.
- processing: reclamado por un proceso.
- completed: sin registros rechazados.
- partial: existen registros aceptados o duplicados y rechazados.
- failed: fallo fatal o ningún registro utilizable.

Un archivo vacío se rechazará con EMPTY_FILE.
Un lote con solo duplicados válidos podrá completarse.

Una empresa o fuente desactivada después de recibir una carga
impedirá iniciar su procesamiento y quedará registrada como error.

### Recuperación tras interrupciones

El reclamo del lote registrará:
- processing_token.
- heartbeat_at.
- attempt_count.

Estos campos se incorporarán al modelo y a la migración
de ingestion_batches.

El proceso actualizará el heartbeat durante su ejecución.
Un lote processing no se reclamará nuevamente de forma automática.

Un comando de recuperación permitirá devolverlo a pending
cuando haya vencido el tiempo de actividad configurado.

El token deberá impedir que un proceso anterior continúe
escribiendo después de perder la propiedad del lote.
La recuperación no borrará observaciones ya incorporadas.

## 8. Idempotencia y duplicados

### Solicitud

El ámbito de Idempotency-Key será empresa y fuente.

- Misma clave y mismo contenido: devuelve el lote existente.
- Misma clave y contenido diferente: HTTP 409.
- La firma considerará hashes de archivos y manifiesto normalizado.
- Los nombres originales formarán parte del manifiesto conservado.

Se agregará request_fingerprint a ingestion_batches para
verificar estas condiciones.

### Observaciones

- Los reintentos aplicarán dedup_key.
- La clave no dependerá del ID del lote.
- Una nueva carga de los mismos archivos no duplicará observaciones.
- No se eliminarán repeticiones legítimas dentro de un archivo.

Para métricas sin identificador del proveedor, la huella incluirá
instante, recurso, métrica, valor, unidad y dimensiones normalizadas.

Para logs del perfil inicial sin identificador estable, se utilizarán
hash del archivo y posición del registro. Esto evita duplicados
del mismo archivo sin confundir entradas repetidas.

Los solapamientos entre archivos distintos de logs no se
deduplicarán por similitud en esta versión. Esta limitación
se mostrará en la documentación del adaptador.

Los registros existentes conservarán la referencia a su primera
ingesta; el nuevo lote contabilizará los duplicados encontrados.

## 9. Archivos y consistencia

- Los originales no se sobrescriben.
- La ruta física se genera usando identificadores internos.
- Cada lote dispone de un espacio propio para sus archivos.
- Los rechazos de registros se documentan en ingestion_errors.
- Un archivo parcialmente válido conserva su original completo.

La recepción utilizará almacenamiento temporal hasta completar
las validaciones y guardar los originales.

Si falla el registro definitivo del lote:
- Se intentará eliminar los archivos creados por esa solicitud.
- Se registrarán los fallos de limpieza.
- No se devolverá una aceptación exitosa.

Un comando de mantenimiento permitirá identificar temporales
y archivos huérfanos, sin eliminarlos indiscriminadamente.

## 10. Configuración inicial

Variables previstas:

- OBSINF_ENV.
- OBSINF_DATABASE_URL.
- OBSINF_DATA_DIR.
- OBSINF_LOCAL_DEV_MODE.
- OBSINF_MAX_FILES_PER_BATCH: default 10.
- OBSINF_MAX_FILE_SIZE_MB: default 20.
- OBSINF_MAX_BATCH_SIZE_MB: default 100.
- OBSINF_MAX_QUERY_DAYS: default 31.
- OBSINF_INGESTION_STALE_SECONDS: default 300.

Los límites se aplicarán durante la lectura de los archivos,
sin cargarlos completos en memoria.

.env no se incorporará a Git.
.env.example incluirá valores de ejemplo sin secretos.

No se requerirá una API key de OpenAI para esta funcionalidad.

## 11. Pruebas de aceptación

### Empresas y fuentes

1. Crear una empresa y obtener un ID numérico.
2. Rechazar un código de empresa duplicado.
3. Rechazar una zona horaria inválida.
4. Crear fuentes con el mismo código en empresas distintas.
5. Rechazar fuentes duplicadas dentro de una empresa.
6. Rechazar una fuente con tecnología sin adaptador habilitado.
7. Impedir nuevas cargas para empresas o fuentes inactivas.

### Ingesta

8. Cargar un log válido y conservar su original.
9. Cargar métricas JSONL y comprobar valores y unidades.
10. Interpretar un log multilínea como un único registro.
11. Registrar errores con archivo y posición de origen.
12. Obtener partial al mezclar registros válidos e inválidos.
13. Rechazar archivos vacíos o con codificación no admitida.
14. Aplicar los límites de cantidad y tamaño.
15. Verificar el hash del original descargado.

### Idempotencia y recuperación

16. Repetir una solicitud y obtener el mismo lote.
17. Reutilizar su clave con otros datos y obtener 409.
18. Cargar nuevamente un archivo sin duplicar observaciones.
19. Conservar dos entradas de log idénticas en posiciones distintas.
20. Reintentar tras una interrupción sin duplicar datos.
21. Impedir el procesamiento simultáneo del mismo lote.
22. Impedir escrituras de un proceso cuyo token haya vencido.

### Aislamiento y consultas

23. Rechazar relaciones entre datos de empresas distintas en BD.
24. No devolver datos de otra empresa desde la API.
25. No permitir descargar archivos de otra empresa.
26. Filtrar métricas y eventos por fuente y período.
27. Aplicar correctamente los límites temporales [from, to).
28. Paginar sin omitir ni repetir filas de un conjunto estable.
29. Impedir el modo local de desarrollo en producción.

## 12. Definición de terminado

La funcionalidad estará terminada cuando:

- Las migraciones puedan aplicarse sobre una BD vacía.
- WebLogic esté disponible en el catálogo.
- Los endpoints estén documentados en OpenAPI.
- El procesamiento funcione mediante el comando independiente.
- Existan fixtures sintéticos para logs y métricas.
- Pasen las pruebas relevantes de aceptación.
- Las pruebas de integridad se ejecuten contra PostgreSQL.
- README explique instalación, migración, carga y consulta.
- .env.example documente la configuración.
- Los archivos originales sean recuperables y verificables.
- No se haya modificado observability-ai-poc.