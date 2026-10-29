# 005 — Especialista Oracle y persistencia de hallazgos

## Objetivo

Interpretar evidencias Oracle persistidas por el detector de normalidad,
usando ADK con OpenAI y el contrato actual de hallazgos de OBSINF.

## Entrada y autorización

- Empresa, ejecución de análisis y fuente Oracle explícitas.
- Ejecución en estado `completed` o `partial`.
- Fuente y ejecución de la misma empresa.
- Evidencias seleccionadas por empresa, ejecución y fuente, agrupadas por recurso.
- Métricas Oracle habilitadas y unidades del contrato común.
- Referencias al perfil y su versión tomadas de la ejecución registrada.

No se seleccionan métricas crudas, eventos WebLogic ni datos de otras fuentes.
La cobertura parcial se indica al operador y en el contexto del agente.

## Contrato

El especialista produce `FindingProposal`: recurso, período, clasificación,
severidad, confianza, descripción y referencias a evidencias. En esta entrega
`event_ids` debe estar vacío. Las implicancias pueden estar vacías.

Se rechazan IDs inexistentes en el contexto, recursos diferentes, períodos
que no cubran las evidencias y campos del contrato anterior del piloto.

## Ejecución

`python -m app.jobs.interpret_oracle` recibe `--company-id`, `--execution-id`
y `--source-id`. Por defecto muestra la propuesta sin guardarla. `--persist`
habilita la persistencia. El comando requiere el modo local actualmente usado
por OBSINF y utiliza el mismo `.env` que WebLogic.

Sin evidencias no se configura ni se invoca al modelo. La llamada al modelo
ocurre sin mantener abierta una sesión de base de datos.

El ejecutor ADK común conserva las sesiones temporales independientes y
recoge solo la respuesta final. Cada especialista mantiene su propia
instrucción, construcción de mensaje y validación de referencias.

## Persistencia

El servicio recibe `expected_technology` desde el llamador autorizado,
no desde el LLM. Su valor predeterminado conserva el flujo WebLogic; el
comando Oracle envía explícitamente `oracle`.

Se verifica que la fuente corresponda a la tecnología esperada. Los nombres
de especialistas conocidos deben coincidir con esa tecnología. Se conservan
los controles por empresa, ejecución, fuente, recurso, evidencias y período.
Oracle todavía no admite contexto ni citas de eventos.

Se permite un hallazgo por ejecución, fuente, recurso y agente mediante el
servicio. Un precontrol del comando evita invocaciones repetidas innecesarias;
la comprobación bajo bloqueo sigue siendo la protección definitiva.

Se reutilizan `findings` y `finding_evidence`. La procedencia queda registrada
con agente, modelo y hash de la instrucción exacta. No se crean tablas nuevas.

## Criterios analíticos

- Conteos de sesiones bloqueadas no equivalen a sesiones bloqueadoras,
  transacciones o usuarios afectados.
- No se suman conteos de instantes distintos como sesiones únicas.
- Tres muestras no prueban continuidad entre ellas.
- No se deducen deadlocks, consultas, objetos, causas raíz ni impacto sin datos.
- No se atribuyen consecuencias a WebLogic sin evidencia y dependencia explícitas.
- No se asume procedencia sintética o real solo por nombres de perfiles.

## Aceptación

- Interpretación Oracle en modo de prueba y persistencia opcional.
- JSON y referencias válidos antes de guardar.
- Aislamiento por empresa, fuente, recurso, tecnología y ejecución.
- Rechazo de eventos no proporcionados.
- Procedencia y evidencias visibles mediante los GET de hallazgos existentes.
- Compatibilidad del flujo WebLogic y su contexto de eventos.
- Pruebas automatizadas sin llamadas externas.
