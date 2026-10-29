# 004 — Primera ingesta de métricas Oracle

Implementa el primer bloque de `003-weblogic-oracle-analysis.md`.

## Alcance

- Tecnología `oracle`, nombre inicial `Oracle Database`.
- Registro de fuentes por empresa.
- Recepción y procesamiento del formato `obsinf_metrics_jsonl_v1`.
- Métricas `oracle_active_sessions` y `oracle_blocked_sessions`.
- Almacenamiento en `metrics_normalized` con procedencia y deduplicación.

No incluye extracción directa, logs Oracle, agente Oracle ni correlación.

## Contrato y capacidades

El parser común valida la estructura y el catálogo de métricas. La política
de capacidades define qué formatos y métricas corresponden a cada tecnología.
El estado activo del catálogo no sustituye la existencia de una integración.

El registro de fuentes, la recepción y el procesamiento consultan la misma
política. El procesador vuelve a validar el formato y la tecnología de cada
métrica para no depender únicamente de la validación de recepción.

`oracle_active_sessions` representa el conteo instantáneo de sesiones de
usuario activas dentro del servicio y contenedor definidos para el recurso.
`oracle_blocked_sessions` representa el conteo instantáneo de sesiones de
usuario de ese recurso con un bloqueador identificado como válido.

Son nombres del contrato OBSINF. Las definiciones deberán aplicarse al futuro
extractor. Ambos valores son conteos enteros no negativos, con unidad `count`.
Un fallo de extracción no se sustituirá por cero.

## Compatibilidad

La implementación de métricas se mueve a `app/integrations/common/`.
La ruta anterior de WebLogic reexporta los mismos objetos, conservando imports
y comprobaciones `isinstance`. Las huellas de las observaciones anteriores
no cambian. El parser se identifica como `obsinf_metrics_jsonl_v1:1.1.0`.

## Errores

- Tecnología sin integración: conserva los errores de negocio existentes.
- Formato incompatible con la tecnología: rechazo de la solicitud completa,
  `422 FORMAT_NOT_SUPPORTED_FOR_TECHNOLOGY`.
- Métrica de otra tecnología: error localizable por línea,
  `METRIC_NOT_SUPPORTED_FOR_TECHNOLOGY`.
- Conteo o unidad inválidos: `INVALID_METRIC`.

La creación del lote sigue siendo idempotente. El procesamiento conserva
los contadores de aceptados, rechazados y duplicados, y sus transacciones.

## Persistencia

Solo se agrega una entrada de catálogo. No se crean tablas nuevas.
Si `oracle` ya existe, no se sobrescribe. La reversión conserva esa entrada
para no eliminar configuración previa ni historial de fuentes.

## Aceptación

- Carga Oracle completa desde API hasta `metrics_normalized`.
- Aislamiento por empresa y fuente.
- Idempotencia y deduplicación entre lotes.
- Restricciones de origen activo, formato y métrica por tecnología.
- Errores por línea con preservación de registros válidos.
- Revalidación de un manifiesto alterado antes de procesar.
- Compatibilidad de imports y huellas de las métricas WebLogic anteriores.
- Regresiones existentes de métricas y logs WebLogic aprobadas en el proyecto.
