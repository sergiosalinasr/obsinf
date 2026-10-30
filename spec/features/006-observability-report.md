# 006 — Reporte de observabilidad

Estado: propuesta de implementación

## Objetivo

Presentar resultados de observabilidad ya guardados en OBSINF,
con trazabilidad hacia hallazgos, correlaciones y evidencias.

## Alcance inicial

- Generación manual por empresa.
- Selección explícita de IDs de hallazgos y correlaciones.
- Formato Markdown.
- Construcción determinista en Python, sin invocar al LLM.
- Conservación del contenido y de los datos utilizados.
- Consulta posterior por API.

No incluye todavía programación, PDF, envío ni chat.

## Selección de información

- Todos los resultados deben pertenecer a la empresa solicitada.
- Los IDs deben ser positivos y no repetirse.
- Una correlación seleccionada incorpora sus dos hallazgos.
- Un hallazgo incorporado por varias referencias se presenta una sola vez.
- No se selecciona automáticamente la interpretación más reciente.
- La ausencia de hallazgos no se presenta como normalidad.

## Período

La solicitud indica un período [inicio, fin), con zona horaria.

Las ejecuciones de análisis incluidas deben cubrir todo el período
solicitado. Los hallazgos seleccionados deben quedar dentro de él.

La primera versión rechaza selecciones incompatibles.
No recorta ni reinterpreta hallazgos.

Las fechas se presentan en una zona horaria explícita.
Cada ejecución conserva su propio corte de recepción.

## Contenido

1. Identificación de empresa y período.
2. Alcance: fuentes y recursos seleccionados.
3. Resumen de resultados incluidos.
4. Hallazgos por tecnología y recurso.
5. Correlaciones entre recursos.
6. Cobertura y cortes de datos de las ejecuciones.
7. Limitaciones.
8. Referencias a IDs de resultados y evidencias.

Los conteos distinguen hallazgos de correlaciones.
Una correlación no se cuenta como otro incidente.

## Interpretación

- Los textos de especialistas se identifican como interpretaciones.
- Las hipótesis no se convierten en hechos.
- TEMPORAL_COINCIDENCE no significa causalidad.
- Se conservan las limitaciones y la procedencia sintética declarada.
- No se agregan recomendaciones ni conclusiones nuevas.

## Conservación

El reporte guarda:

- Empresa y período solicitado.
- Zona horaria de presentación.
- IDs de resultados seleccionados.
- Copia de los datos utilizados.
- Contenido Markdown generado.
- Versión del generador.
- Fecha de generación.

Cambios posteriores en dependencias o resultados no modifican
el reporte guardado.

## Validaciones de aceptación

- Rechazar referencias de otras empresas.
- Rechazar IDs inexistentes y selecciones incompatibles.
- Evitar hallazgos duplicados.
- Conservar los cortes de datos individuales.
- Mostrar cobertura parcial cuando corresponda.
- No interpretar falta de datos como operación normal.
- Mantener las referencias y limitaciones.
- Generar el mismo contenido para la misma entrada y versión
  del generador, sin incluir fechas variables dentro del contenido.
- Consultar el reporte sin invocar al LLM.