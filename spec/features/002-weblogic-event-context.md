# Contexto de eventos para interpretar evidencias WebLogic

## Objetivo

Relacionar evidencias métricas deterministas con eventos normalizados cercanos
del mismo recurso. El agente interpreta el conjunto, sin atribuir causalidad
solo por cercanía temporal. Python selecciona y valida los datos disponibles.

## Selección

- Misma empresa, ejecución, fuente WebLogic y recurso.
- Solo eventos con `received_at <= analysis_executions.data_cutoff_at`.
- Ventana inclusiva desde `evidence.start_at - margin` hasta
  `evidence.end_at + margin` por cada evidencia.
- Se consulta la unión de ventanas; no se llena el espacio entre desviaciones
  lejanas y no se duplican eventos que caigan en ventanas superpuestas.
- Orden por `occurred_at`, luego `id`, ambos ascendentes.
- Margen predeterminado 120 segundos; configurable entre 0 y 3600.
- Máximo predeterminado 100 eventos por recurso; configurable entre 1 y 100.
- Cada mensaje se limita a 2000 caracteres. El servicio admite hasta 4000;
  el comando utiliza 2000. Se conservan los indicadores de recorte.
- Se selecciona una fila adicional para detectar `has_more_events`.
- No se envían los atributos arbitrarios del log, archivos raw ni secretos
  de configuración de fuentes. El texto de mensajes se trata como datos.

Los eventos tardíos requieren una nueva ejecución de análisis. No se modifica
el corte de una ejecución existente para incorporar información posterior.

## Contrato del agente

`FindingProposal` incorpora `event_ids`, lista opcional que por defecto es vacía.
Solo admite enteros positivos, sin repeticiones y hasta 100 referencias.

Cada ID debe estar en la selección entregada al agente y ser cercano a una
evidencia citada por el mismo hallazgo. El período del hallazgo debe cubrir
las evidencias y los instantes de los eventos citados. La proximidad temporal
no demuestra continuidad, impacto, causa raíz ni saturación de un pool.

La ausencia de eventos en la selección no equivale a ausencia de errores.
El prompt debe reconocer la selección parcial y los mensajes recortados.

## Cambios de datos

### Ampliación de `findings`

| Campo | Tipo | Regla |
| --- | --- | --- |
| `event_context` | JSONB | Obligatorio, objeto, predeterminado `{}` |

El objeto vacío representa un hallazgo sin contexto registrado (incluye los
anteriores a esta versión). Un contexto registrado conserva empresa, ejecución,
fuente, recurso, corte de recepción, límites, ventanas, eventos enviados y
banderas de recorte. Los mensajes guardados son exactamente los fragmentos
enviados al agente. La API los devuelve en `event_context`.

### Nueva tabla `finding_events`

| Campo | Tipo | Regla |
| --- | --- | --- |
| `id` | BIGINT IDENTITY | Clave primaria |
| `company_id` | BIGINT | Obligatorio |
| `finding_id` | BIGINT | Obligatorio |
| `event_id` | BIGINT | Obligatorio |

- FK compuesta `(company_id, finding_id)` a `findings(company_id, id)`.
- FK compuesta `(company_id, event_id)` a `events_normalized(company_id, id)`.
- Unicidad de `(company_id, finding_id, event_id)`.
- Índice `(company_id, finding_id)`.

Las FK garantizan pertenencia a la misma empresa. El servicio comprueba además
fuente, recurso, selección autorizada, cercanía, corte y período del hallazgo.
Se guarda la asociación solo para eventos citados; los eventos considerados
pero no citados permanecen en la copia del contexto para auditoría.

## Persistencia y API

La selección se vuelve a consultar antes de guardar. Si cambió respecto de la
enviada al agente, la operación se rechaza. Hallazgo, evidencias, asociaciones
a eventos y contexto se confirman en la misma transacción.

Los GET de listado y detalle incorporan `event_ids` y `event_context`.
Las referencias se ordenan por ID y siempre se consultan dentro de la empresa.
Los hallazgos antiguos devuelven `event_ids: []` y `event_context: {}`.

No se sobrescriben hallazgos existentes. Se conserva la regla de un hallazgo
por ejecución, fuente, recurso y agente mediante el servicio actual.

## Validación

Las pruebas cubren aislamiento por empresa, fuente y recurso, corte inclusivo,
ventanas separadas y superpuestas, selección y recorte deterministas, referencias
inventadas, períodos inválidos, cambios del contexto, persistencia atómica,
compatibilidad de hallazgos previos, consultas e integridad de las asociaciones.

Las pruebas automatizadas usan propuestas sintéticas y no llaman a OpenAI.
