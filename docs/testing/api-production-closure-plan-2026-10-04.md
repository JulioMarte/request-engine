# API adversarial review and production closure plan — 2026-10-04

Última actualización: 2026-10-06. Los checkpoints fechados al final son históricos;
el estado actual de esta sección prevalece sobre frases «en ejecución» de esos checkpoints.

## Reporte simple (para humanos)

El alcance es API, seguridad, contratos, pruebas y operación. El panel y Chrome
quedan fuera por petición del usuario. La meta no es aumentar el número de
endpoints: es permitir configurar, consultar, cambiar, recuperar y explicar cada
proceso sin SQL, sin permisos implícitos y sin otra implementación detrás del panel.

Esta pasada corrige problemas concretos de permisos actuales, formularios
costosos, recuperación del formulario original de solicitudes y documentación
automática de errores. No constituye una auditoría exhaustiva ni una aceptación
de producción. La evidencia final se registra abajo, separada de las propuestas.

Persisten trabajos que no deben esconderse: la protección transaccional nueva
no cubre todas las operaciones antiguas. El trabajador de limpieza segura ya
está implementado, pero permanece desactivado hasta verificar sus condiciones
de seguridad en el despliegue. El correo productivo necesita un proveedor y
configuración verificados. Las pruebas locales no sustituyen los controles
de infraestructura ni la validación de GitHub.

Revisión posterior de preparación: la API tiene recorridos reales de usuarios,
permisos, invitaciones y descubrimiento de operaciones; no vuelven a contarse
como funciones ausentes. El defecto de errores inesperados sin seguimiento
ya está corregido y probado. La renovación de credenciales de agentes conserva
su identidad y tiene pruebas de rechazo y concurrencia. Su recorrido positivo
externo pasó en Docker, incluida retirada y restauración de política.
Las restricciones que impiden
a un agente concederse permisos son intencionales, no funciones por habilitar.
MCP, SDK distribuido y administración granular de sesiones son ampliaciones
distintas; no deben confundirse con seguridad productiva ya aceptada.
Hay límites de entrada, trabajo de contraseñas y consultas de base de datos
implementados y probados; falta aceptar la infraestructura real y su carga.
Si el producto promete procesar solicitudes hasta terminarlas,
hay que cerrar su consumidor autorizado; sus operaciones internas no deben
publicarse sin diseño. La guía de pasos puede ser más precisa y la repetición de
operaciones antiguas necesita una política expresa. Suspender y revocar agentes
sí está disponible. Las organizaciones nuevas no tienen el problema de adopción
de permisos de las antiguas. Hay monitoreo implementado, pero falta demostrarlo
en el entorno real. La batería completa anterior falló en consumidores del
contrato de onboarding; sus expectativas y prerrequisitos fueron corregidos.
La repetición completa terminó correctamente. Una revisión adicional encontró
pérdida de precisión al recibir precios como números decimales JSON: ya está
corregida y pasó las pruebas específicas y la batería general final. La primera invocación del
runner no encontró psql en el PATH; se corrigió el entorno, sin omitir comprobaciones.
La aprobación de esa batería no equivale a estar listo para producción.

## Reporte técnico (detallado)

### Autoridad y método

AC-20/AC-21, última reanudación:

- `platform/http/exact_decimal.py::admit_exact_decimal` es admisión técnica,
  compartida por tres DTO; no mueve reglas monetarias de owners a platform.
  `BaseTermsBody`, `ContextTermsBody`, `SupersedeTermsBody` aceptan str/int y
  Decimal Python tipado; rechazan float/bool, incluso1.0. Null solo en Booking.
  DTO owners: `catalog/api/operational_schedule_router.py` y
  `booking/api/operational_terms_router.py`. Registro de error en
  `booking/api/operational_errors.py`, `booking/api/__init__.py` y composición
  `entrypoints/http/error_handlers.py`; adapters en
  `booking/adapters/db/contextual_config_commands.py` y
  `booking/adapters/db/contextual_terms_supersession_commands.py`.
- `booking/application/commands/configure_booking_context_terms.py::validate_context_terms_amount`
  protege configure/supersede y sus adapters antes de receipts/DB: finitud,
  rango14/6 y representación acotada. `BookingTermsInvalidInput` tiene handler
  owner422, instalado por API del módulo y composición global; no catch global
  de ValueError. No DDL, cambios de capacidades, rutas, operationIds o privilegios.
- Catalog `validate_booking_terms_input` ahora elimina ceros significativos
  con índice, no slices repetidos O(n²), en
  `catalog/application/commands/configure_offering_version_booking_terms.py`.
  Medición local del caso16002caracteres:
  antes0.258769s, después0.001923s; no load/SLA proof. Las4 pruebas preservan
  semántica válida/inválida, no son una aserción de tiempo ni una prueba de carga.
- Focal agente: PostgreSQL18.6,50801,head0025,56 PASS46.48s; contratos/unit23 PASS1.71s;
  Ruff12files PASS/Pyright12files0errors. Revisión independiente readonly:
  probes de precisión Decimal1 con traps, DTO/owner extremales y7 pruebas PASS.
  Root regresión de handler global +padding20 PASS14.50s.
- Quality final `.ci/api-closure-quality-money-20261006`:12 pasos PASS/exit0,
  arquitectura202/24.93s, unit1079/81.15s(1warning), módulos752/14.88s.
- Runner `.ci/api-closure-current-product-money-20261006`: **PASS/exit0**,
  PostgreSQL18.6 aislado50798, head0025. Sus24 XML tienen cero fallos/errores/skips.
  Schema37, business-info14, comandos113, contextual-booking21, autoridad463;
  E2E457 PASS/1087.79s (2 deselected por selección, no skips); booking-capacity17,
  secret-store9, seguridad operativa74. Los demás grupos también completados.
  `proof-execution.json`:380 archivos ejecutados, `gaps: []`.
  Fuente comprobada antes/después idéntica:2197 entradas SHA256
  `91055F0488BC116364CCA7B8D32FC37A54277563073A334ACCE1A78FD8DF79E6`.
  Alcance de huella: `.py/.sh/.sql/.toml/.json` en src/tests/migrations/scripts,
  más pyproject.toml,uv.lock y current-guarantees.toml; no Markdown ni assets UI.
  Esta evidencia local no es CI exact-head ni certificación de publicación.

Verificación de entorno del 2026-10-06: el contenedor local PostgreSQL18.6
conserva bases distintas. `request_engine_current`, destino predeterminado de
`scripts/dev/run_local_panel.ps1`, está en `0025_agent_credential_rotation`.
`POSTGRES_DB=request_engine` es la base predeterminada histórica del contenedor
y registra `0055_authority_inspect_policy`; no es el destino predeterminado del launcher.
La consulta no demuestra por sí sola qué DSN usa cualquier proceso ya abierto.
No se migró ni borró esa base histórica. Seleccionar el destino explícitamente,
no inferirlo de POSTGRES_DB, y nunca ejecutar fixtures destructivas sobre5432.

Branch `feature/admin-console`, integration lane homónimo. `origin/development`
resuelto el 2026-10-04: `1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`, igual al merge
base del HEAD local. Árbol ya sucio antes de la revisión; sus cambios se preservan.
No rebaseline, borrado de datos del usuario, UI, Chrome, commit ni push en esta
pasada. Tras la batería amplia se añadió una migración de reducción de permisos;
su aceptación se registra separadamente abajo. La instalación local del panel
no es la base de pruebas.

Fuentes de autoridad: garantías actuales, docs 07/13/15/16, contratos de owners
y política de evolución. Revisión paralela de Requests/consumo de recursos,
autoridad transaccional y API journey/contratos. Las observaciones estáticas,
las pruebas HTTP con puertos simulados, PostgreSQL real y aceptación de proveedor
son evidencias distintas; ninguna se presenta como certificación universal.

Referencias externas primarias, consultadas en esta pasada:
[OWASP consumo de recursos](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/),
[OWASP autorización de funciones](https://api-security.owasp.org/editions/2023/en/0xa5-broken-function-level-authorization/),
[AIP-158 paginación](https://google.aip.dev/158) y
[OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html).
Para AC-20, el schema del tipo admitido antes de conversión se contrasta con
[Pydantic: validators y JSON Schema](https://docs.pydantic.dev/latest/concepts/validators/#json-schema-and-field-validators).
Se usan como criterios de revisión, no como reemplazo de contratos propietarios.
La elección del motor se contrasta con la [documentación oficial RE2](https://github.com/google/re2):
matching sin backtracking, presupuesto configurable y sintaxis deliberadamente
restringida. No convertir esa propiedad del motor en una promesa de coste lineal
de toda la validación JSON, HTTP o igualdad mediante hashing.

### Hallazgos y disposición

| ID | Riesgo / evidencia de origen | Tratamiento en esta pasada |
| --- | --- | --- |
| AC-01 P0 | Snapshot de capability en ingress podía autorizar administración después de retirar el grant; confirmado por inspección de adapters | Check transaccional estrecho con Principal SHARE antes de leer grants actuales; pruebas de ambos órdenes y replay. Alcance exacto en el contrato enlazado abajo |
| AC-02 P0 | Requests ejecutaba regex Python sin garantía de coste acotado | RE2, presupuesto de compilación, patrones y árbol JSON; no fallback de backtracking. Adaptación preproducción explícita; datos históricos no se reescriben |
| AC-03 P1 | Inbox daba UUID de versión, pero lectura del schema exigía definition_id y versión numérica; no podía reconstruirse el formulario antiguo sin guardar recibos | Metadata vinculada al tenant y versión exacta del request; viaje v1 → publicación v2 → inbox → lectura v1 |
| AC-04 P1 | OpenAPI anunciaba HTTPValidationError aunque el handler global devuelve ErrorEnvelope; Requests omitía errores de negocio relevantes | Proyección global sustituye solo el schema predeterminado; owner declara sus errores reales. No cambia statuses ni crea otro protocolo |
| AC-05 P2 | Disponibilidad, revisiones, autoridad Party y continuidad de páginas no eran evidentes en los nuevos GET | Descripciones OpenAPI útiles y guía de composición/retry; no nuevo registro de política |
| AC-06 P0 operativo | Inventario/TTL no equivalen a limpieza definitiva segura | Worker acotado implementado en 0024, con lease, resultados durables y admisión explícita; desactivado por defecto. Revisión técnica independiente focal realizada; aceptación productiva y revisión formal exact-head pendientes |
| AC-07 P1 operativo | Invitation create puede quedar queued sin worker; SMTP aceptado no implica aceptación de invitación | Recuperación e invitación de staff por API/worker/OpenBao/Mailpit ya aprobadas en Docker. Falta aceptación del proveedor, configuración gestionada y operación productivas |
| AC-08 P1 evidencia | Verde local o subconjuntos antiguos no certifican el commit final | Repetir calidad, PostgreSQL canónico y pruebas afectadas tras estabilizar el árbol; exact-head CI y revisión formal pendientes |
| AC-09 P1 diagnóstico | Schema almacenado malformado/profundo se confundía con payload inválido y pedía al cliente corregir su demanda | Separar admisión de schema persistido del documento; error de configuración 500 con operator_intervention, publicación inválida y payload inválido siguen 422. Declarar 500 en operaciones Requests afectadas |
| AC-10 P1 privilegios | Batería amplia detectó acceso SELECT/INSERT a toda la tabla de recibos de creación nativa, introducido en 0017 y ausente del inventario revisado | Forward 0023 restringe a SELECT de cinco columnas e INSERT de seis; proyección explícita en el primitivo. No ampliar el inventario con los permisos innecesarios ni reescribir 0017 |
| AC-11 P1 adopción | Controllers de tenants anteriores a policy v6 no reciben automáticamente los nuevos permisos administrativos | Adopción sigue propuesta en ADR 0016; no regalar grants ni confundir metadata visible con acceso. Documentar estado y decidir migración explícita por owner |
| AC-12 P1 consumidor | Suite Docker alcanzó claim/login reales pero su creación nativa omitía Idempotency-Key y recibió 422 | Actualizar el consumidor al contrato del Command, con key estable por intención; no quitar el requisito del API ni añadir keys indiscriminadamente a ceremonias |
| AC-13 P1 concurrencia, corregido y probado en alcance | Principal SHARE → Representation SHARE frente a Representation UPDATE → trigger Principal UPDATE en los nuevos adopters produjo deadlock con rol app real | Conexión estrecha bajo Principal lock lee Representation sin rowlock, conserva validación Party y serialización por trigger. 16 pruebas PostgreSQL PASS; no declarar seguridad universal ni aprobación de toda la batería |
| AC-14 P1 listado, corregido y probado | Docker real reproduce 500 en GET staff/invitations sin after: psycopg no determina el tipo del UUID nulo | CAST UUID explícito en ambas posiciones. Docker real ahora verifica página inicial, continuación, página vacía y aislamiento; no se evita el GET con cursor artificial |
| AC-15 P1 diagnóstico, corregido y probado | Excepción inesperada atravesaba middleware/handlers reales y devolvía 500 text/plain sin X-Correlation-ID | Fallback técnico sanitizado y correlación en factories principales y parciales; conserva respuestas de owners y no recomienda reintentos ciegos |
| AC-16 P1 concurrencia, corregido y probado | Dos primeras creaciones de channel policy con keys distintas podían leer ausencia y el perdedor recibía unique23505/500 | ON CONFLICT estrecho conserva ganador; reread y conflicto tipado409. Prueba determinística con dos PID y efectos durables exactos |
| AC-17 P1 admisión, corregido y probado | Horarios inválidos y ubicación ausente/ajena llegaban a errores internos; términos podían redondearse o desbordar numeric | DTO/Command/adapter rechazan valores inválidos; precio exacto14/6, ceros finales válidos, exponentes extremos rechazados. Igual conflicto409 para Location ausente/ajena; prueba sin efectos |
| AC-18 P1 consumo externo, corregido y probado | Timeout por chunk no acotaba respuesta metadata interminable ni buffering de POSTdestroy | GET5s total/raw64KiB/sin compresión y POST5s sin consumir cuerpo; reconciliación y lease fence preservados. No certifica proveedor real |
| AC-19 P2 guidance, corregido y probado | Guía confundía business-Party con root/controller y negaba una operación válida | Blocker empresarial apunta a parties_register, sin prometer provisioning o grants; controller/authentication mantiene intervención separada |
| AC-20 P1 transporte, corregido y verificado | JSON decimal se convierte a float antes de Decimal: 99999999999999.111111 pierde precisión aun cuando pasa la admisión numeric; Booking admite overflow y exponentes extremos | Rechazar float/bool en las tres entradas monetarias; aceptar texto decimal exacto y enteros, OpenAPI coherente y reglas monetarias owner antes de recibos. HTTP crudo/PG56 PASS; quality, runner completo y revisión independiente PASS |
| AC-21 P2 coste, corregido y verificado | Quitar ceros con slices repetidos de tupla cuesta O(n²) | Índice descendente O(n), misma semántica. Cuatro pruebas de ceros largos y fracción no admisible; quality, runner y revisión independiente PASS; no certificación de carga |

### Cambios y límites del diseño

1. `platform/db/tenant_principal_authority_reader.py` incorpora
   `require_current_tenant_capability`; Requests definición Commands y nuevas
   Queries administrativas Requests/Catalog/Booking/Communications lo consumen.
   La principal serialization root evita inversión Principal/grant: no se toman
   locks de filas de grant después del Principal. Los writers existentes actualizan
   authority_revision. No expansión ACL/RLS ni DDL.
   [Contrato y alcance](../architecture/administrative-transaction-authority.md).
2. Requests `domain/schema_validation.py` limita admisión de patrones y recorrido
   JSON, y elimina comparación pairwise de `uniqueItems` con identidad JSON
   estructural tipada. Validar sintaxis segura al publicar; legacy incompatible
   falla como configuración inválida, no instruye al cliente a reintentar ciegamente.
3. Requests inbox añade metadata para identificar definición y versión originales;
   su join conserva igualdad tenant. No agrega payload sensible a la bandeja.
4. `platform/http/errors.py::install_validation_error_schema` y
   `entrypoints/http/error_handlers.py::add_global_error_handlers` alinean 422
   generado con el handler real y preservan respuestas explícitas de owners.
5. Booking/Catalog/Communications describen lectura previa, Party authority,
   revisiones y paginación en sus routers. La
   [guía para clientes](../architecture/api-client-journeys.md) explica el recorrido.
6. `tenancy/api/staff_invitations.py` declara `NativeSessionBearer` en preview y
   accept pretenant. El contrato exige sesión nativa, no un bearer genérico ni
   tenant header; la autenticación real no se debilita ni cambia.
7. `migrations/versions/0023_native_provision_receipt_columns.py`, revisión
   `0023_native_receipt_columns` desde `0022_native_provision_session`, elimina
   privilegios de tabla del definer de control para los recibos de creación.
   Mantiene firma, owner y validaciones del primitivo; un anchor único exige
   reemplazar solamente la proyección de replay. No borra datos ni hace backfill.
   Su reversión es roll-forward, no reintroducción automática de permisos amplios.

No se establece revocación retroactiva de transacciones ya admitidas. No se
afirma que se revalidan transaccionalmente sesiones, binding, delegación, features
o política de agentes en todas estas operaciones. Tampoco se retrofita cada
Command antiguo: eso exige revisión del contrato y orden de locks de cada owner.
Las nuevas Queries HTTP no se convierten automáticamente en herramientas MCP.

### Plan restante con criterios de salida

#### Revisión actual: producción no equivale a CRUD universal

Fuentes actuales y revisión readonly de tres agentes, más comprobación del agente
principal. Sin cambios productivos, concesiones, migraciones o pruebas sobre DB5432
en esta revisión. `git fetch origin development` confirmó el mismo base
`1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`; HEAD local sigue
`e4f65b59eae4fcc032f3b7effc0550c165fe6ee7`, con árbol no comprometido.

El objetivo verificable es un cliente capaz de autenticar, descubrir su contexto,
preparar una operación, consultar su estado/revisión, ejecutarla con autoridad,
reconciliar incertidumbre y reconstruir el resultado sin SQL. No es exponer todas
las tablas ni otorgar a agentes el control de instalación/autoridad humana.

| Prioridad y categoría | Trabajo pendiente | Criterio de salida verificable |
| --- | --- | --- |
| P1, defecto corregido | AC-15: fallback implementado y probado; falta certificación integrada | Excepción inyectada responde ErrorEnvelope sanitizado y correlation; nada de SQL/secretos/tracebacks. Conservar statuses específicos y ausencia de reintento automático ante resultado desconocido |
| P0 operativo, promesa de retención | AC-06: worker implementado; admisión productiva pendiente | Worker lease/fence + resultado durable, inspección/reconciliación, roles negativos y carreras reales. No certificar borrado de backups con destroy del proveedor |
| P0 de lanzamiento, entorno | Admisión TLS/ingress privado, roles/ACL, correo, restore y alertas | Ejecutar aceptación contra entorno real, no sustituirla por Mailpit. Restore/clone bloquea outbound; monitoreo y worker detectan fallos reales |
| P1, protección de recursos | Presupuestos HTTP/CPU/SQL implementados y probados; carga/ingress real pendiente | Bytes reales acotados con y sin Content-Length; carga y hashing acotados; sobrecarga/cancelación/rollback probados. No asumir controles externos no inspeccionados |
| P1 funcional para agentes persistentes | Rotación y metadata implementadas en 0025; pruebas focales y recorrido Docker aprobados | Command del owner conserva principal/grants/policy, secreto solo en respuesta permitida, token anterior rechazado y reconciliación segura; conservar certificación integrada y pruebas de autoridad |
| P1 de evidencia de integración | Agente positivo y cliente externo/schema | Provisionar/activar/grants/policy por API; catálogo→schema→owner permitido; retirar política→denegación; replay/revisión/decimal/error con cliente externo, sin fixtures que fabriquen resultados |
| P1 condicionado a tenants antiguos | AC-11: adopción de política | Aceptar gobernanza y transición manifest-bounded; root antiguo adquiere derechos solo por viaje autorizado. Fresh install v6 no necesita esa adopción |
| P1 condicionado al producto prometido | Procesamiento de Requests hasta terminar | Definir consumidor/worker autorizado y probar submit→proceso→resultado sin publicar indiscriminadamente comandos internos |
| P1 de coherencia contractual | Replay de Commands antiguos | Owner define admisión y autoridad del resultado durable; si cambia, pruebas de retirada y orden de locks. No confundir receipt namespace y grant capability |
| P1 de publicación | Certificación final del árbol integrado | Runner canónico exit0, calidad/revisión semántica sobre revisión correcta, pre-push y GitHub exact-head antes de merge |
| P2 de integración | Readiness→acciones y documentación vigente | Blocker apunta a operación montada o receta con requisitos/revisiones; validar referencias sin otro registro de política. Corregir instrucciones de instalación antiguas |
| P2 opcional | MCP, SDK empaquetado, sesiones/dispositivos selectivos | Solo si se incluyen en el producto prometido: proyectar owners existentes y probar equivalencia/autoridad; no segundo backend ni administración tenant implícita de sesiones globales |

**Evidencia y límites de los hallazgos nuevos:**

- Root reprodujo AC-15 mediante `uv run python -c $taskDiagnosticSource`:
  FastAPI mínimo con `add_global_error_handlers` y `_request_execution_context`,
  ruta diagnóstica que levanta RuntimeError, HTTPX ASGITransport con
  `raise_app_exceptions=False`. Resultado: `500 text/plain; charset=utf-8`,
  correlation ausente, cuerpo `Internal Server Error`. Sin red, auth o PostgreSQL;
  no se ejecutó la factory completa. Fuentes: `entrypoints/http/app.py:75-82`,
  `error_handlers.py::add_global_error_handlers`. Control-plane comparte handlers;
  su alcance adicional es inspección estática, no reproducción completa.
- Presupuestos: `platform/db/session.py::create_postgres_engine` no configura
  statement/lock timeouts; `bootstrap/settings.py` limita el probe, no toda consulta.
  Requests limita el árbol después de parsing. `native_human_auth.py` usa
  `asyncio.to_thread` para hashing; no se encontró admisión agregada de ese trabajo
  en la composición revisada. No es prueba de saturación ni de valores externos
  de PostgreSQL/ingress. Referencia primaria: [OWASP API4](https://api-security.owasp.org/editions/2023/en/0xa4-unrestricted-resource-consumption/).
- Agentes: `tenancy/api/agent_governance_routes.py` ofrece provisionar, autoridad
  y estado; suspensión/revocación sí existen. No ofrece la rotación específica
  disponible para Integration en `integration_governance_routes.py`.
  Ausencia de rotación no equivale a ausencia de revocación. La lectura AgentView
  tampoco reconstruye metadatos/expiración de sus credenciales.
- `tests/e2e/test_native_agent_lifecycle.py` ya prueba catálogo filtrado y policy;
  el sistema Docker `_exercise_agent_zero_authority` prueba denegación inicial.
  Falta el positivo externo integrado, no la implementación de catálogo.
- Requests monta `include_internal=False` deliberadamente. Result/complete/fail
  no son operaciones públicas ausentes por accidente. Decidir quién consume
  demandas antes de prometer su lifecycle completo en producción.
- `onboarding/api/router.py::project_readiness` devuelve varios blockers sin
  operation_id; capability por sí sola no identifica una acción única.
- `http-runtime-deployment.md:3-9,32-34` presenta claim como futuro/CLI inicial,
  aunque el viaje HTTP ya pasó Docker. El UUID de autoridad configurado sigue
  requerido por settings/composición: corregir esa distinción, no quitar variables.
- Existe telemetría en `deploy/observability` y launcher OTel. No se acepta el
  monitoreo productivo por su mera presencia ni se afirma que no existe.

Orden recomendado: cerrar AC-15 y presupuestos; terminar pruebas/certificación;
implementar/admitir limpieza segura y entorno; completar credenciales/recorrido
positivo de agentes; resolver Requests y políticas antiguas según alcance; después
readiness/SDK/MCP. El transporte MCP no es un requisito para usar HTTP con agentes.

**Checkpoint previo (2026-10-05):** el runner AC13 terminó con exit1: E2E registró
455 PASS / 2 FAIL / 2 deselected; los dos defectos del consumidor/inventario
HTTP fueron corregidos y tuvieron 10 pruebas focales PASS. El runner sobre
0025 aprobó principal-authority (457 casos), pero se detuvo por tres firmas
nuevas ausentes del inventario cerrado de EXECUTE. Tras revisar sus límites se
añadieron únicamente esas firmas; inventario/privilegios/rotación: 5 PASS.
Se reinició el runner completo en `.ci/api-closure-current-product-head25-20261006`.
Los grupos posteriores y proof-map siguen sin certificación completa; no mezclar
resultados parciales de ejecuciones distintas para afirmar exit0.

#### 1. Autoridad y contratos administrativos restantes

Inventariar los Commands existentes Catalog/Booking/Communications/Requests por
su owner y establecer para cada uno el punto de autorización/replay. Priorizar
configuración de canales, offering policy y supply. Aplicar el mismo mecanismo
solo donde sus locks sean compatibles; no hacer un wrapper global de comandos.
El namespace de receipt/audit no es necesariamente una capability pública:
por ejemplo, `catalog.set_offering_version_booking_policy` y
`communications.set_channel_policy` identifican intenciones internas, mientras
la autorización HTTP usa `catalog.manage` y `communications.configure`.
Usar el primer namespace como argumento del helper de grants rompería operaciones;
resolver siempre la capability publicada en metadata del owner.

Para organizaciones antiguas, la adopción de nuevos permisos por sus controllers
no está completada: [ADR 0016](../adr/0016-existing-controller-policy-adoption.md)
continúa propuesta. Definir el nuevo contrato de adopción y su autoridad antes
de aplicarlo; un permiso nuevo visible no autoriza a delegarlo. No usar grants
automáticos ni un reset destructivo implícito como sustituto de esa decisión.

Salida: operación admitida primero puede terminar antes de revoke; revoke
ganador deniega; replay no revive permisos. Pruebas PostgreSQL independientes
bajo rol real, locks observados, cero writes/receipt/outbox tras rechazo. Revisar
por separado política de agentes, delegación y autenticación, sin mezclarlas.

#### 2. Cierre de secretos temporales

Seguir el [contrato de inventario/worker](../architecture/temporary-proof-cleanup-inventory-proposal.md):
append-only resultados, work row/lease/fence, roles técnicos separados, claim
committed antes de provider I/O, inspección antes de destroy y reconciliación
de resultados ambiguos. Apéndice de migración desde el head efectivo, nunca
reescribir 0013/0020 ni el baseline.

Admission exige backend UUID no reutilizado, mount/namespace cerrado, políticas
efectivas de **todos** los writers/operadores sin metadata DELETE/recreation,
fencing de restore y pruebas de carreras reales. El worker no debe tener
plaintext read, LIST recursivo, metadata DELETE ni autoridad de negocio.
No backfill inventado de versiones sin recibo confiable.

Salida: lease loser no finaliza; crash y destroy ambiguo reconcilian; versión
nueva no se destruye; ACL negativas reales; auditoría durable sin secretos.
Destroy del proveedor sigue sin certificar borrado de medios o backups.

#### 3. Correo de invitación extremo a extremo por API

Proveer un Principal INTEGRATION legítimo mediante owner API, login DB restringido,
publisher real y configuración SMTP/secret store coherente; usar la composición
worker existente, no SQL para fabricar autoridad ni publisher no-op.
Crear invitación por API, observar delivery, obtener el correo en destino de
prueba aislado, autenticar destinatario, preview/accept y aplicar derechos.

Salida: creación/retry/resend/revoke/expiry, fallo definitivo y ambigüedad de
proveedor, aceptación de único uso y membership sin grants implícitos. Para
producción: proveedor real, dominios/remitente, TLS y secretos, conectividad,
reconciliación y alertas de pendientes. Captura en Mailpit no prueba entrega externa.

#### 4. Journey, agentes y SDK

Ejecutar pruebas de reconstrucción tras descartar las respuestas de creación;
consumir schemas desde OpenAPI y operation-catalog, no desde una segunda lista.
Auditar tipos cerrados, errores accionables, continuación, revisión e idempotencia
por flujo crítico. Documentar diferencias de cursor antes de migrar contratos.

Clasificar opt-in tools por owner/operation/capability y audiencia: discovery
no autoriza ejecución. La proyección MCP preserva los mismos tipos y restricciones;
no necesita duplicar el backend. No exponer automáticamente los Commands internos
de procesamiento de Requests: esa frontera deliberada necesita diseño de worker.

Salida: cliente humano/dev y agente autorizado pueden preparar y reconstruir
estado sin SQL; agente no puede fabricar contexto o modificar autoridad; un
cliente generado interpreta los errores reales sin analizar mensajes.

#### 5. Certificación y despliegue

Terminar la batería PostgreSQL canónica, repitiendo los grupos importados antes
de los últimos cambios; completar Python quality y revisión semántica sobre el
SHA correcto. Publicar solo con certificación pre-push y exigir GitHub exact-head.
No usar verde anterior como evidencia del árbol actual.

Validar configuración productiva explícita: HTTPS/private control ingress,
cookies cuando proceda, aislamiento DB, roles/ACL providers, secretos y rotación,
timeouts/rate limits, worker readiness, migración clean-install y upgrade,
backup/restore con outbound fencing y alarmas. No se dispone aquí de un entorno
productivo cuya aceptación pueda declararse.

Los límites de Requests siguen ejecutándose después de interpretar JSON, pero
ahora las cinco factories HTTP instalan además admisión de bytes reales antes del
parser, deadline y concurrencia acotada. Hashing usa un presupuesto independiente
que no se libera prematuramente por cancelación; los bootstraps HTTP limitan SQL,
locks y espera del pool. Son límites por proceso, no un rate limiter distribuido
ni prueba de capacidad de una infraestructura productiva. Exigir todavía límites
efectivos en ingress, conexiones, compresión y carga real. RE2 no certifica todo
el presupuesto de memoria ni el coste del transporte.

### Evidencia ejecutada y estado

#### Reanudación 2026-10-05/06: estado actual, no certificación productiva

- Forward `0024_temporary_proof_cleanup` añade claim/finalize técnicos, lease,
  resultado append-only y rol `request_proof_cleanup_worker`; `0025_agent_credential_rotation`
  añade tres funciones estrechas para manager/rotación/metadata. Clean install y
  multibase PostgreSQL 18.6 PASS. No cambio del baseline ni datos de usuario.
- `platform/http/request_budget.py` admite bytes reales, deadline y concurrencia
  antes del parser en las cinco factories; probes tienen presupuesto separado.
  `platform/security/password_work.py` acota hashing y mantiene el permiso hasta
  terminar el thread aunque se cancele el consumidor. `platform/db/execution_budget.py`
  configura statement/lock/transaction/idle/pool para los bootstraps HTTP, no workers.
  Evidencia focal SQL real con asyncpg/psycopg: 9 PASS; combinación con onboarding:
  17 PASS. HTTP/errors/validación: 39 PASS; CPU/autenticación/HTTP: 48 PASS.
  Son conjuntos superpuestos, no sumarlos como pruebas independientes.
- Catalog readiness usa únicamente la versión más reciente de Offerings activos.
  Defecto reproducido antes del fix (3 FAIL / 1 PASS); después, 11 PASS junto con
  discovery contextual bajo LOGIN restringido. Onboarding ofrece cinco operation IDs
  montados y recetas cuando no existe una reparación automática: 8 pruebas PASS.
- Inventario/worker/rotación focal en Docker PG18.6 aislado: 35 PASS, 21.83 s.
  La limpieza sigue outbound-fenced, sin scheduler ni destroy productivo. Sus
  condiciones de admisión/restore y revisión independiente final siguen pendientes.
- Quality sobre head0025 `.ci/api-closure-quality-head25-20261006`: exit0,
  arquitectura202, unit1072, módulos748, lint/formato/tipos y seguridad PASS.
  Repetición posterior `.ci/api-closure-quality-channel-20261006`: exit0.
  El último cambio de Catalog es posterior a sus primeros pasos: aún requiere
  calidad completa final; no presentar un verde previo como certificado del árbol.
- Docker reveló primero stdout CRLF en el launcher y después configuración
  opcional vacía de invitation URL que rompía el arranque. Correcciones en
  `scripts/ci/e2e_suite_registry.py`, `scripts/ci/run_e2e_suite.sh` y
  `bootstrap/staff_invitation_delivery.py`; URL no vacía insegura sigue rechazada.
  Regresión focal de configuración y bytes CLI: 19 PASS; Ruff/Pyright focal PASS.
- Primer Docker funcional de agentes detectó un GET inexistente en el consumidor.
  Se cambió a lookup publicado con oracle independiente del ID, no se añadió
  un endpoint para hacer verde el test. `f01-foundation`: exit0 en
  `.ci/api-closure-docker-head25-20261005-agent-retry`; claim, WebAuthn, grants/policy,
  operación positiva, rotación/replay/metadata, token viejo rechazado y suspensión.
  Ejecución ampliada con retirada/restauración de política: exit0 en
  `.ci/api-closure-docker-head25-policy-final-20261006`. Retirada conserva grants
  y produce 403 `capability_required`; restauración vuelve a permitir lookup.
  Dos expectativas iniciales del consumidor usaron códigos incorrectos: se
  corrigió el test al contrato de intersección de capabilities, no el API.
- Rotación adversarial: 7 PASS, 8.50 s en PG18.6 aislado50801. Rechazo de target
  extranjero/revocado, AGENT y manager con permiso no delegable; estado de
  credenciales/recibos/audit/revisiones sin cambios al denegar. Dos transacciones
  bloqueadas observadas desde otra conexión prueban una sola rotación, tanto con
  misma key como con keys distintas (perdedor stale sin receipt/audit).
  Primera preparación falló porque intentaba mutar un grant inmutable y porque
  contaba solo bloqueos directos; se corrigió el fixture y el oracle transitivo,
  no se debilitaron triggers ni guardas del producto.
- Runner `.ci/api-closure-current-product-head25-20261005`: exit1 en inventario
  EXECUTE después de principal-authority457 PASS. Se revisaron y registraron las
  tres firmas exactas de 0025 sin wildcard ni nuevos privilegios de tabla; focal
  inventario/privilegios/rotación: 5 PASS. Runner completo
  `.ci/api-closure-current-product-head25-20261006`: exit1; E2E 452 PASS / 5 FAIL,
  2 deselected, 1171.48 s. Los cinco consumidores de onboarding conservaban
  expectativas anteriores a resolution_hint/operationId; dos además carecían de
  grants persistentes para configurar Catalog/Communications. Se adaptaron sus
  contratos esperados y prerrequisitos explícitos sin relajar autorización.
  Focal posterior onboarding/Catalog: 16 PASS, 27.62 s, PG18.6 aislado50801.
  La ejecución global se detuvo antes de grupos finales; necesita repetición.
- Quality `.ci/api-closure-quality-owner-guards-20261006`: exit0, unit1072,
  módulos748, lint/formato/tipos y restantes pasos PASS. Los cambios posteriores
  de pruebas/creación concurrente todavía requieren nueva validación integrada.
- Subagentes pudieron reanudar revisión el 2026-10-06. La revisión final todavía
  no está cerrada globalmente. Catalog completó revisión independiente de cleanup
  y ejecutó sus 20 pruebas unitarias (PASS, 5.29 s); no encontró otro defecto.
  Esto no prueba permisos reales del proveedor ni reemplaza evidencia PG.
- Base local de uso diario actualizada con `uv run alembic upgrade head` hasta
  0025, PostgreSQL18.6. Consultas antes/después: identidades1, organizaciones0,
  principals1, sin cambios. Rol cleanup NOLOGIN/NOSUPERUSER/NOBYPASSRLS.
  No borrado ni activación outbound/scheduler ni reinicio de API. El puerto
  Docker5432 permanece publicado en todas las interfaces: no certifica ingress
  privado/productivo y requiere configuración de despliegue apropiada.
- Communications configure y Catalog offering-policy adoptan explícitamente
  admisión de standing grant + Party/Representation antes de idempotencia. No
  namespaces internos como permisos, nuevas ACL ni otras rutas de ejecución.
  Antes del fix cada owner produjo 3 FAIL confirmando replay permitido tras
  retirar grant/Representation/Party. Communications final: 11 PASS/14.09s con
  cuatro carreras, ambos órdenes, locks observados y estado negativo completo.
  Combinación final Catalog/Communications/supply reader: 33 PASS/41.63s, sobre
  PG18.6 aislado50801. Catalog añadió cuatro carreras, dos tipos de retirada,
  ambos órdenes: bloqueo observado y ganador/perdedor con efectos durables
  exactos; sus diez pruebas pasan en el focal de 16 citado arriba.
  esta adopción no declara transaccionalmente revalidada toda autenticación/política.
  El runner global ya había importado algunos grupos antes de estos cambios:
  incluso si termina exit0 necesitará repetición integrada sobre fuente estable.
- Revisión independiente reprodujo carrera de primera creación de política:
  ausencia no es una fila bloqueable. `_upsert_policy` usa ahora ON CONFLICT
  estrecho, conserva ganador y devuelve conflicto de revisión al perdedor.
  Pre-fix unique23505; después Communications 12 PASS/14.77s, PG18.6 aislado57814.
  La prueba está incluida en semantic-commands del runner canónico.
- Cierre de presupuesto externo cleanup: GET metadata raw máximo64KiB y deadline
  total5s, rechazo de compresión; POST destroy con total5s sin consumir cuerpo.
  Siempre reconciliar por metadatos, nunca reintentar a ciegas. Autor:20 PASS5.32s;
  reviewer independiente:20 PASS5.29s. Sin tráfico destructivo real ni DDL.
  Root repitió worker/inventory PostgreSQL + boundary unit con fuente final:
  38 PASS/28.82s, PG18.6 aislado57814, head0025. El primer intento usó un nombre
  de archivo inexistente (0 pruebas); no se cuenta como evidencia.
- Base de integración reconsultada con `git fetch origin development` el
  2026-10-06: origin/development y merge-base siguen
  `1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`; HEAD local
  `e4f65b59eae4fcc032f3b7effc0550c165fe6ee7`, lane feature/admin-console.
  Los cambios aún están en working tree, no certificados como commit publicado.
- Nuevos defectos de Catalog: días/ventanas inválidos y Location ausente/ajena
  alcanzaban errores internos; numeric(20,6) podía redondear mientras receipt/audit
  conservaban otro importe. DTO y Command/adapter ahora rechazan entrada inválida
  con errores tipados; Location ausente/ajena comparte409, precios no-finitos,
  exceso de precisión y exponentes extremos422. Ceros finales equivalentes son
  válidos; no hay redondeo oculto. Fuente final focal17 PASS22.81s PG18.6 aislado50801.
  `test_catalog_schedule_admission.py` añadido a la lane semantic-commands.
- Root corrigió su propia guía de business-Party: el reader comprueba un Party
  empresarial activo, NO el root/controller. Blocker apunta a `parties_register`
  con `parties.register`; registro no concede Representation ni provisiona root.
  Seis operation IDs resolubles y controles separados. Módulo8 PASS4.57s;
  journeys/Catalog/concurrencia final32 PASS48.45s en PG18.6 aislado50801.
- Runner `.ci/api-closure-current-product-final-20261006`: exit1 tras
  principal-authority463 PASS491.31s; antes schema37/business-info14/
  semantic-commands59/contextual-booking21 PASS. Root editó el script mientras
  bash lo ejecutaba: cambio de offsets provocó lectura parcial `-tb=short`.
  Es un error de ejecución de evidencia, no fallo de un endpoint; no contar
  como verde completo. Runner reiniciado con script estable en
  `.ci/api-closure-current-product-stable-20261006`; terminó exit0. E2E457 PASS,
  2 deselected/996.96s; principal-authority463 PASS; comandos semánticos74 PASS;
  regresión booking-capacity17 PASS; secret-store9 PASS; P7 operational-safety74 PASS.
  `proof-execution.json`: 380 archivos ejecutados, gaps vacío. Fuente comprobada
  antes/después idéntica (2194 entradas SHA256
  `6663C0CEA53BA4C68A604A757690CDDA58E2A4C92350EE5F25D4060EF15560D4`).
  Ese resultado precede AC-20/AC-21; no se presenta como prueba global posterior
  a esas correcciones ni como aceptación de infraestructura productiva.
- Quality final primer intento falló Ruff por dos líneas de test largas. Formato
  corregido sin cambio semántico; `.ci/api-closure-quality-final-retry-20261006`
  terminó exit0: arquitectura202, unit1076 (1 warning), módulos748; los12 pasos
  PASS. Ruff global posterior y módulo de onboarding8 PASS verifican las
  aserciones finales. No equivale a certificación de publicación/merge.
- Los paquetes `.ci/quality-evidence/QR-7ce31b8ba060.json` y
  `QR-b14901988a74.json` identifican tested/source SHA
  `12e55a542fdcbb705641841d25681094822dc1e3`, distinto del árbol actual.
  Disposición de actualidad: INSUFFICIENT_CONTEXT. No reutilizar esas revisiones;
  regenerar contexto/packets y revisión semántica del commit candidato antes
  de publicación. El signal scan no es un evidence packet ni una dispensa HARD.
- Sigue pendiente: contrato/replay de Commands antiguos por owner, decisión ADR0016,
  consumidor autorizado de Requests si se promete procesamiento integral,
  aceptación productiva de infraestructura/correo/restore, revisión semántica formal
  y exact-head GitHub. No panel, Chrome, borrado, activación cleanup, commit ni push.

Registro en progreso; completar resultados finales antes de entregar. No asumir
PASS de un proceso aún activo ni de un caso que solamente figura en una guía.

- `uv run pytest tests/unit/test_http_validation_schema.py
  tests/unit/test_http_authentication_contract.py -q --tb=short`: **8 passed**.
- `uv run pytest tests/unit/test_http_validation_schema.py
  tests/modules/booking/test_supply_configuration_http.py
  tests/modules/catalog/test_catalog_configuration_http.py
  tests/modules/communications/test_channel_configuration_http.py -q --tb=short`:
  **6 passed** después de propagar Principal trusted a Catalog.
- Pyright focal de `platform/http/errors.py` y `entrypoints/http/error_handlers.py`:
  **0 errores** después de corregir tipado desconocido detectado en la primera pasada.
- Regresión final de autenticación/ceremonias y validación: **43 passed**, 17.74 s.
  Incluye declaración de sesión nativa para invitaciones sin tenant header.
- Requests final tras corrección AC-09: **55 passed**, 2.68 s, incluidos dos
  casos ASGI con router, validator y error handler reales, pero puertos simulados.
  Ruff y Pyright focales PASS. No prueba rollback DB ni autenticación nativa.
- PostgreSQL 18.6 desechable independiente, puerto 62248, instalación limpia
  0001 → 0022: supply/Catalog/Requests **17 passed**, 53.89 s, ambos órdenes de
  concurrencia observados con conexiones independientes y rol restringido real.
  Requests journey focal adicional **2 passed**, 10.54 s. El contenedor y su
  volumen anónimo fueron eliminados tras las pruebas; datos desechables no
  recuperables. No se eliminó información de la instancia del usuario.
- Primera batería `ci_jobs.py python-quality`: PASS, arquitectura **201**, unit
  **994**, módulos **739**. Posteriormente cambió metadata de invitaciones y AC-09;
  la segunda batería se interrumpió sin resultado final y no se cuenta como PASS.
- Tras la interrupción, `ci_jobs.py python-quality` reiniciado: **PASS**,
  arquitectura **201**, unit **995** y módulos **747**, con Ruff, Pyright,
  secret scan, SAST, dependencia y lockfile PASS. Artefactos en
  `.ci/api-closure-quality-resumed-20261004`. El scanner usó su base por defecto
  `HEAD^`, no la base de publicación `origin/development`; no es certificación
  de publicación ni evidencia formal exact-head. 0023 aún requiere reproof final.
- Segunda batería sobre 0023 con `FILE_BUDGET_BASE_REF=origin/development`:
  **PASS** de todos los pasos. Log/summary
  `.ci/api-closure-quality-head23-20261004`. La evolución del comprobador multibase
  recibió además Ruff/Pyright focales y **10** pruebas unitarias PASS. Los **141**
  sensores no bloqueantes abarcan cambios previos del branch, no 141 fallos;
  su revisión formal de paquetes y el SHA final no quedan certificados por este verde.
- 0023 en PostgreSQL 18.6: **21** pruebas nativas PASS en la primera ejecución;
  topología final **14 PASS**, 111.26 s, tras reconocer cuatro lecturas temporales
  legítimas de invitaciones introducidas en 0016. Instalación multibase limpia
  0001 → 0023 PASS con oracle independiente de columnas y ausencia de table ACL.
  La instancia local del usuario `5432/request_engine_current`, previamente
  verificada en 18.6/head0022, recibió `uv run alembic upgrade head` y lectura
  posterior confirmó `0023_native_receipt_columns`. Sin borrar datos.
- Docker `recovery-delivery`, mundo propio sin puertos publicados: en ejecución.
  Primer intento: build Linux/RE2 y migración 0022 PASS, pero launcher Windows
  produjo nombre de servicio con CRLF y falló antes de arrancar runtime. Proyecto
  limpiado; segundo intento normaliza solo stdout de la herramienta anfitriona,
  sin cambiar la suite ni sus garantías. No cuenta como aceptación de delivery.
  Diagnóstico posterior: alias Git Bash `/tmp` montaba un directorio inexistente
  de Docker VM; adaptación anfitriona mediante `cygpath` preservó archivos y ACL.
  Intento 5 alcanzó claim/WebAuthn/login y falló 422 por AC-12 antes del worker.
  El build o la preparación parcial no se presentan como aceptación de correo.
  AC-12 corregido en cinco llamadas nativas del consumidor; **2** unidades PASS,
  Ruff/Pyright PASS. Intento 6: prepare-worker completo PASS mediante HTTP real,
  incluyendo identidades, organización, autoridad, Principal INTEGRATION y worker
  saludable. Resultado final: **PASS**, exit 0, preparación **15** checkpoints y
  principal **7** (incluyen aislamiento y cierre de suite; no son 22 journeys).
  Recovery real envió proof mediante worker/OpenBao/Mailpit y consumió recuperación
  exactamente una vez. API/control/worker: imagen
  `sha256:8570d8e8731b4c261e1d89348abd3d1feb71aa0408b03d89016a0d7f814ce0a8`.
  Artefactos `.ci/docker-e2e-api-proof-20261004-attempt6/recovery-delivery`.
  Cleanup automático confirmó ausencia de containers/networks/volumes propios.
  La recuperación no certifica el journey distinto de invitación de staff,
  entregabilidad externa, ACL productivas ni borrado de secretos. La prueba de
  invitación específica está en preparación, no se cuenta como PASS.
- `./scripts/dev/test_local_panel_delivery.ps1 -RunRealProviders`: **PASS** de
  KV-v2 deadline/read/ACL negativas y SMTP realmente capturado en Mailpit local.
  Sin PostgreSQL, worker de invitaciones ni aceptación del destinatario.
- `scripts/ci/run_current_product.sh` sobre PostgreSQL 18.6 aislado
  `127.0.0.1:55433/request_engine_admin_verify`, head 0022: baseline limpio y
  segunda DB llegaron correctamente al head. Grupos iniciales schema **37**,
  business-info **10**, semantic-commands **25**, contextual-booking **21** PASS.
  El grupo principal-authority terminó con **346 casos, 1 fallo** en el inventario
  de columnas del definer de control, origen de AC-10; el runner se detuvo y no
  ejecutó sus grupos posteriores. Algunos grupos corrieron antes de estabilizar
  cambios y deben repetirse. Dos intentos de preparación fallaron antes de pruebas por
  falta de migration URL y elección errónea del login aislado; no son fallos de API.
  Se inició una ejecución completa nueva sobre head0023 en
  `.ci/api-closure-current-product-head23-20261004`: se interrumpió. Los XML
  completos registran schema **37**, business-info **10**, semantic-commands **29**
  y contextual-booking **21**, todos sin fallos. Principal-authority contiene
  solo **113** casos sin fallos, no el grupo completo; falta terminar esa batería
  y sus grupos posteriores. No se considera runner aprobado.

Tras reanudar: la suite específica de invitación añadió wiring gobernado de store
y URL confiable al mundo Docker. Correo y rechazo de invitación revocada se
ejecutaron, pero el recorrido no está aprobado: alcanzó AC-14. La primera
expectativa de 404 para una invitación revocada se corrigió a su contrato real
409 `staff_membership_conflict`, sin cambiar el API. Pruebas focales del consumidor,
privacidad del enlace y arquitectura: **22 PASS**. En ese checkpoint AC-13/AC-14
seguían en trabajo; los resultados posteriores se registran a continuación.
Regresión focal del agente principal tras recuperar el árbol: **72 PASS**, 18.12 s
(Requests, validación OpenAPI, autenticación HTTP, transporte de provisioning y
oracle multibase). No reemplaza las pruebas globales y de concurrencia pendientes.

Resultado posterior de invitaciones: **PASS**, exit 0, preparación **15** checkpoints
y principal **10**, en `.ci/docker-e2e-api-proof-20261004-invitations3/recovery-delivery`.
La misma imagen `sha256:0e17ef6d3dad48fadc227034b0c1a58885376e7fae2c6767611a3249351b2315`
ejecutó API/control/worker. Prueba con correo real del entorno aislado: revocación
409 sin membership; create/retry una generación; listado y cursor UUID sin fuga
tenant; preview privado y aceptación pretenant con replay de los mismos IDs;
membership cero grants con denegación403; plan y asignación únicamente de
`authority.read_self`, no delegable; lectura propia y administración staff aún
denegada. Recuperación de contraseña y rechazo de su segundo consumo siguen PASS.
No se probó espera real de una hora para expiry ni SMTP gestionado productivo:
el entorno usa su fallback SMTP explícito. Se verificó cleanup del proyecto.
Focales finales del agente: **24 PASS**, Ruff/formato/Pyright PASS. El barrido
estático de otros filtros SQL no halló otro caso confirmado de parámetro nulo
sin tipo; esa revisión no sustituye ejecutar todos los endpoints con PostgreSQL.

AC-13: reproducción roja del guard anterior, **1 FAIL / 9 deselected**, 10.87 s,
con `DeadlockDetectedError` y conexiones independientes bajo rol app. Es evidencia
del defecto, no una aprobación. La conexión corregida pasó **16 pruebas**, 112.21 s,
en PostgreSQL 18.6 aislado, puerto55433, head `0023_native_receipt_columns`:
`test_supply_configuration_reads.py` y `test_request_definition_administration.py`.
Incluye ambos órdenes entre consulta y retirada de representación, Party inactiva,
retirada de grants y rechazo del replay de definición. Architecture: **202 PASS**,
24.53 s; Ruff/Pyright focal PASS. No DDL ni privilegios nuevos para esta corrección.
La adopción es exclusivamente Booking supply reader, Communications channel reader
y Requests definition management; el guard antiguo permanece intacto.

Validación Python global tras AC-13: `uv run python scripts/ci/ci_jobs.py
python-quality --log-dir .ci/api-closure-quality-ac13-20261004 --summary-output
.ci/api-closure-quality-ac13-20261004/summary.json`, con base
`origin/development`: **todos los pasos PASS**, exit0; arquitectura **202**,
unit **1009**, módulos **747**. Incluye lint/formato/tipos, auditoría de
dependencias y análisis estático de secretos/seguridad. Es evidencia local del
árbol en ese checkpoint, no CI exact-head ni certificación de publicación.

Runner PostgreSQL canónico reiniciado en
`.ci/api-closure-current-product-ac13-20261004`: baseline independiente y segunda
base al head0023 PASS; grupo schema **37 PASS**, 249.66 s. Al escribir este
checkpoint los demás grupos siguen en ejecución, **runner no aprobado**.
No se mezcla con el runner anterior interrumpido para fabricar una aprobación.
Revisión independiente readonly del fix AC-13 no encontró otro blocker confirmado.
Sus dos huecos de evidencia se cubrieron después: Party concurrente y Commands
de definición frente a Representation, ambos órdenes. En Docker PostgreSQL18.6
independiente, loopback62946, `authority_proof`, instalación 0001→0023 y
READ COMMITTED confirmado: ambos archivos completos **20 PASS**, 71.72 s.
Con los límites de espera finales, las seis carreras afectadas **6 PASS**,
35.50 s (14 deselected); Ruff/Pyright focal PASS. Requests prueba exactamente
una definición/versión/receipt/audit si gana y ausencia de esos efectos si pierde;
outbox permanece vacío y replay posterior se deniega. Party se desactiva dejando
Representation/grants activos para aislar su protección. El primer intento de
las dos carreras Requests falló en el oracle por nombre de tabla incorrecto
(`outbox_events` en lugar de `outbox_messages`); se corrigió el test, no el producto.
Se eliminó únicamente el contenedor y volumen de ese cluster desechable.

El protocolo tiene un instante de admisión, no garantiza que la representación
no expire antes del commit. La conexión está diseñada para READ COMMITTED;
no reutilizarla automáticamente dentro de snapshots REPEATABLE READ.
La quality global se repitió con estas pruebas adicionales en
`.ci/api-closure-quality-ac13-extra-20261004`: **todos los pasos PASS**, exit0.
Arquitectura202, unit1009 y módulos747; no reemplaza la ejecución global
PostgreSQL todavía pendiente ni la certificación exact-head.

Checkpoint del runner PostgreSQL AC13: esquema **37 PASS**, información de
negocio **10 PASS**, comandos semánticos **37 PASS**, reservas contextuales
**21 PASS**. Incluye la nueva carrera Party dentro del grupo de comandos.
Principal-authority está en ejecución; sus casos parciales no se cuentan como
grupo aprobado. Los grupos posteriores todavía no han terminado. No informar
que `run_current_product.sh` pasó hasta obtener exit0 y revisar su evidencia.

Inventario adversarial de escrituras antiguas: Catalog offering-policy,
Communications channel configure y Booking supply/context terms pueden devolver
receipts completadas antes de validar representación. Eso no vuelve a ejecutar
la mutación: devuelve su resultado durable anterior. Hace falta decidir por owner
la autoridad exigida para ese replay antes de endurecer su contrato. No adoptar
nombres de receipts como capacidades: por ejemplo, el permiso es `catalog.manage`,
no `catalog.set_offering_version_booking_policy`. No se implementó un retrofit
global ni se infiere una violación HARD universal de esta asimetría.

No despliegue productivo, borrado de organizaciones, modificación del panel ni Chrome en
esta pasada. No aceptación SMTP externa, janitor productivo ni CI del commit
exacto. El head de migración se informa como checkpoint, no como techo permanente.

## Addendum de revisión y validación (2026-10-06)

El hallazgo de replay administrativo se resolvió de forma acotada en los owners
Catalog y Booking: los Commands de configuración que usan una Representation
operativa ahora validan el scope exacto antes de `acquire_idempotency`. Una
revocación que gana el root de autoridad impide leer una respuesta durable
anterior; una operación ya admitida conserva el orden de serialización existente.
No cambian capabilities, payloads, revisiones, receipt namespaces, migraciones ni
grants. El test E2E real de Booking asignación cubre crear, replay válido, conflicto
por reutilización de clave con distinto fingerprint y replay denegado después de
revocar la Representation. La cobertura específica por cada otro Command y ambos
órdenes de carrera todavía no existe; no se considera adversarialmente cerrado.

Evidencia de este checkpoint, PostgreSQL 18.6 aislado en el contenedor
`request-engine-http-budget-proof-20261005`, puerto 50798, base
`request_engine_budget_verify`, head0025:

```text
uv run pytest tests/e2e/test_operational_supply_idempotency.py -q --tb=short
1 passed in 10.81s

uv run pytest \
  tests/integration/f1_operational_profile/test_operational_profile_commands.py \
  tests/integration/f1_operational_profile/test_operational_commands.py \
  tests/integration/f1_operational_profile/test_catalog_schedule_admission.py \
  -q -m postgres --tb=short
60 passed in 101.69s

uv run python scripts/ci/ci_jobs.py python-quality
exit 0; Python budget, environment, lockfile, Ruff, format, Pyright,
secret scan, SAST, dependency audit, architecture, unit and module tests PASS.
```

El intento de `bash scripts/ci/run_current_product.sh` no pudo iniciarse en este
host Windows: `bash.exe` apunta a WSL, pero `/bin/bash` no está instalado. El
runner completo no se informa como aprobado para este checkpoint. La PR #137
apunta a `development` y sus checks estaban verdes para el commit anterior
`e4f65b59`; eso tampoco certifica este árbol modificado.

La adopción de permisos para tenants antiguos permanece propuesta en ADR0016 y
no está implementada. El upgrade de política actual no habilita a un controlador
v3 solitario a salir de su techo delegable. No se hizo backfill, no se restauró
ningún permiso revocado y no se borraron organizaciones. Resolverlo exige aceptar
y probar un flujo de consentimiento tenant + aprobación de plataforma con una
capacidad de plataforma alcanzable; la revisión también encontró una inconsistencia
histórica en la evidencia de provisión del primer owner que debe reconciliarse.
