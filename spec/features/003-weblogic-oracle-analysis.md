# 003 — Análisis conjunto WebLogic y Oracle Database

## Objetivo

Analizar problemas de uso de conexiones JDBC en WebLogic junto con
condiciones observadas en el servicio Oracle utilizado por la aplicación.

El resultado debe distinguir hechos, relaciones configuradas,
coincidencias temporales y conclusiones que los datos no permiten establecer.

Esta capacidad será la base del primer reporte conjunto y del chat.

## Escenario inicial

Durante un mismo período:

- WebLogic presenta desviaciones en conexiones JDBC y puede registrar
  solicitudes de conexión fallidas o esperas.
- Oracle presenta sesiones bloqueadas o variaciones de sesiones activas.
- Existe una dependencia explícita entre el datasource WebLogic y
  el servicio Oracle analizado.

No se atribuye causalidad únicamente por coincidencia temporal.

## Alcance inicial

1. Registrar Oracle Database en el catálogo de tecnologías.
2. Crear una fuente Oracle por empresa.
3. Recibir métricas Oracle mediante archivos JSONL.
4. Reutilizar la normalización y el almacenamiento de métricas existentes.
5. Configurar reglas de normalidad y generar evidencias Oracle.
6. Incorporar un agente especializado en Oracle.
7. Registrar la dependencia WebLogic–Oracle.
8. Producir una interpretación conjunta con referencias verificables.

La primera entrega utilizará archivos y datos sintéticos.
La extracción directa desde Oracle se implementará posteriormente.

## Identificación de recursos

La relación debe identificar:

- Empresa.
- Fuente WebLogic.
- Servidor y datasource WebLogic.
- Fuente Oracle.
- Base o PDB y servicio Oracle.

Ejemplos de claves de recurso para la demostración:

- WebLogic: ManagedServer1/ERP_DS
- Oracle: ORCLPDB1/ERP_SERVICE

Son identificadores de ejemplo, no nombres descubiertos automáticamente.

Las métricas existentes de ManagedServer1 no se atribuirán
retroactivamente a ERP_DS sin información que lo respalde.

La coincidencia en empresa, nombre o período no crea una dependencia.
La dependencia debe registrarse explícitamente y conservar su procedencia.

## Métricas Oracle iniciales

### oracle_active_sessions

- Unidad: count.
- Tipo: medición instantánea.
- Cuenta sesiones de usuario con estado ACTIVE dentro del servicio
  y contenedor definidos para el recurso.
- No equivale al número de conexiones activas del pool WebLogic.

### oracle_blocked_sessions

- Unidad: count.
- Tipo: medición instantánea.
- Cuenta sesiones de usuario del recurso que tengan un bloqueador
  identificado como válido.
- No equivale al número de sesiones bloqueadoras.
- No acredita por sí sola impacto sobre usuarios ni sobre WebLogic.

La definición y el ámbito deben mantenerse constantes entre muestras.
Un fallo de extracción no se representará como valor cero.

## Datos de demostración

Se prepararán muestras alineadas temporalmente para ambas tecnologías:

1. Operación dentro del perfil configurado.
2. Desviaciones JDBC y sesiones bloqueadas en períodos coincidentes.
3. Desviaciones JDBC sin sesiones bloqueadas observadas.
4. Datos Oracle ausentes o incompletos.

Los umbrales serán propios de la demostración.
No se presentarán como recomendaciones universales de operación.

## Reutilización

Reutilizar, cuando corresponda:

- Empresas, tecnologías y fuentes.
- Recepción, manifiestos e idempotencia.
- Procesamiento de lotes y control de duplicados.
- metrics_normalized.
- Perfiles, reglas y detector de desviaciones.
- Ejecuciones, evidencias y referencias a mediciones.
- Contrato de hallazgos y servicios de consulta.

Las validaciones específicas de WebLogic deben separarse de las
capacidades comunes antes de habilitar Oracle.

No se copiará íntegramente el piloto sin revisar sus contratos,
dependencias y supuestos de empresa o escenario.

## Interpretación conjunta

El análisis conjunto utilizará:

- Una dependencia explícita válida para el período analizado.
- Evidencias autorizadas de la misma empresa.
- Períodos y cortes de recepción identificados.
- Hallazgos especializados y sus referencias.
- Información de cobertura y datos faltantes.

Debe diferenciar:

- Condiciones detectadas en WebLogic.
- Condiciones detectadas en Oracle.
- Coincidencia temporal entre ambas.
- Evidencia adicional necesaria para establecer una relación causal.

La ausencia de datos no se interpretará como normalidad.
Los datos sintéticos se identificarán como tales.

## Criterios de aceptación

- Se reciben y consultan métricas Oracle sin mezclar empresas.
- Las definiciones de las métricas son explícitas y reproducibles.
- Las reglas generan evidencias con referencias a las muestras.
- El agente Oracle no utiliza evidencias de otra fuente o empresa.
- La dependencia no se deduce de nombres ni de proximidad temporal.
- Sin dependencia registrada, no se afirma una relación de aplicación.
- El análisis reconoce datos faltantes y cobertura parcial.
- Las conclusiones conservan referencias a sus evidencias.
- El funcionamiento existente de WebLogic conserva sus pruebas.