# Handoff adversarial: administración de organizaciones, personas y permisos

Fecha: 2026-09-29. Rama: `feature/admin-console`. Estado: revisión y plan de
remediación, **no aprobación de producción ni contrato nuevo aceptado**.
Auditoría del trabajo local publicado en `e38b7e5d`, reconciliado con los cuatro
commits remotos hasta `069075da` mediante `917c2f01`. Usar `git log` para resolver
el commit final que contiene este documento. Las líneas citadas son orientativas;
las funciones y rutas son los anclajes estables.

## Reporte simple (para humanos)

El panel permite llegar a operaciones reales, pero todavía no ofrece un recorrido
administrativo seguro y completo. Una pantalla de permisos puede ocultar cambios
que el comando sí ejecutará. Un fallo de red puede afirmar falsamente que nada
cambió. Los miembros después de la primera página quedan fuera del recorrido y
la pantalla conserva datos antiguos después de guardar.

Tampoco existe la invitación por correo. Agregar una identidad existente requiere
identificadores técnicos y luego activar su membresía. Ser administrador de la
plataforma no convierte automáticamente a alguien en administrador de cada
organización; el panel debe explicar esa diferencia y ofrecer un camino autorizado.

Las pruebas anteriores aprobaron partes concretas, pero no demostraron el viaje
completo de una persona nueva hasta trabajar dentro de su organización. Esta
revisión reprodujo fallos del panel con APIs simuladas y revisó el código de
autoridad. Los escenarios de permisos concurrentes y sesiones entre organizaciones
necesitan nuevas pruebas con PostgreSQL. La base local principal sigue una
migración por detrás de la rama.

Este handoff conserva los defectos para que otro agente los remedie por prioridad.
En esta pasada se incorporaron las correcciones remotas del dashboard y se
preparó la publicación del trabajo existente. No se implementaron las nuevas
invitaciones ni las correcciones de permisos descritas abajo.

## Reporte técnico (detallado)

### Alcance, autoridad y evidencia

- Propietario de organizaciones, membresías y concesiones: `tenancy`.
- `communications` debe poseer intención/entrega de correo; el proveedor es adaptador.
- Panel/BFF: composición de APIs, nunca acceso SQL ni autoridad alternativa.
- Normas: `docs/15-api-design-and-usability-standards.md`, doc 16,
  `docs/testing/current-guarantees.toml`, política de evolución continua.
- Revisiones SQL futuras: apéndices desde el head resuelto, sin editar `0001`.
- Se realizó `git fetch origin`: development permaneció en `1f0d3fcc`; la rama
  remota avanzó de `55e09612` a `069075da`. Se preservaron ambos trabajos.
- Evidencia ejecutada en esta auditoría: probes ASGI/httpx con la aplicación y
  ejecutor reales y upstream simulado; lectura SQL/código; decodificación de una
  cookie **sintética**; inspección de versión y Alembic local. No se enviaron
  invitaciones, no se modificaron usuarios reales ni se reprodujeron carreras SQL.
- PostgreSQL local, contenedor `request-engine-postgres-1`, puerto 5432, base
  `request_engine_current`: PostgreSQL **18.6**, Alembic
  **0002_discoverable_webauthn_login**. Rama: **0003_platform_org_directory**.
  No se migró la base funcional durante una auditoría de solo lectura.
- Evidencia de la pasada anterior (no repetida aquí): cuatro pruebas focales en
  PostgreSQL 18 limpio migrado a 0003 y lane `python-quality` aprobada. Esa prueba
  no incluye los escenarios adversariales nuevos de este documento.
- Después de reconciliar remoto: `uv run pytest tests/unit/admin_console -q`:
  **63 passed**. Una aserción previa esperaba texto crudo del upstream en el
  dashboard; se adaptó al resumen visual conservando 200, error HTTP visible y
  ausencia de pantalla de excepción. Se conserva prueba remota que prohíbe llamar
  deployment recovery plan al cargar dashboard. La reconciliación cambió
  `routes_operations.dashboard` a proyección de readiness, sin consultar proveedor.
- Hook administrado instalado con `uv run python scripts/dev/install_git_hooks.py`.
  La publicación debe certificar el commit final; consultar salida de push y
  `.git/request-engine/push-certifications/` para SHA/base/resultados. Este documento
  no convierte esa certificación de Python en evidencia PostgreSQL/E2E.

### Hallazgos priorizados

#### A01 · P1 · El plan omite revocaciones que sí ejecutará el comando

Código: `modules/tenancy/adapters/db/staff_membership_reader.py:156`,
`plan_authority`; `migrations/baseline/0001_schema.05.sql:748`,
`replace_staff_authority`. El plan une los grants del objetivo con el techo
delegable del actor. Calcula `removed` sobre ese subconjunto. El comando revoca
todos los grants activos omitidos en la lista deseada.

Reproducción SQL pendiente: actor activo con `staff.manage_authority`, sin
delegación de `appointments.read`; objetivo ordinario con ese permiso. Plan de
`desired_capabilities=[]`: `current=[]`, `removed=[]`, `assignable=true`.
PUT idéntico: revoca `appointments.read`. Contradicción confirmada estáticamente;
no afirmar escalada de privilegios sin decidir la semántica de revocación.

Remediación: decidir en el contrato si se reemplaza toda la autoridad o solo la
administrable. Recomendación: impedir cambios ciegos sobre autoridad fuera del
alcance administrable. Si se preservan grants ajenos, adaptar el comando SQL y
plan juntos mediante migración nueva. Si se permite revocarlos, bloquear o
advertir con un contador opaco de cambios no visibles, sin revelar sus nombres.
La política debe vivir en el owner y el comando debe revalidarla bajo locks.

Aceptación: prueba PostgreSQL plan→apply sobre mismo estado; diferencia anunciada
coincide con persistencia. Cubrir techo vacío, permiso ajeno, objetivo controlador,
cambio de revisión y revocación concurrente del poder del actor. El test actual
`test_staff_overview_and_authority_plan_are_read_only_and_ceiling_bounded` exige
ocultar un grant pero no aplica el resultado: ampliarlo sin debilitar la privacidad.

#### A02 · P1 · Timeout ambiguo comunicado como ausencia de cambios

Código: `admin_console/execution.py`, `_HUMAN_ERRORS`, `execute_operation`,
`local_error`; `templates/resources/staff*.html`.
Probe ejecutado con `httpx.ReadTimeout`: mensaje `Nothing was changed`,
`idempotency_key=None`. Dos envíos staff sin `_intent_id` producen claves distintas.
Una respuesta puede perderse después del commit; el mensaje actual no es demostrable.

Remediación: resultado `outcome_unknown`, conservar clave y cuerpo normalizado de
la intención; permitir replay con la misma clave o reconciliar por lectura/recibo.
Crear intención estable al renderizar y rotarla al completar o cambiar el borrador.
Nunca reintentar automáticamente un cuerpo editado con la clave anterior.
No inferir que cualquier error de transporte significa rollback.

Aceptación: upstream confirma un efecto y pierde respuesta; reintento mantiene
clave/cuerpo y recupera el único resultado. Prueba de mensaje con stub y prueba
de efecto único/idempotencia con PostgreSQL. Verificar refresh y doble clic.

#### A03 · P1 de producto · No existe invitación por correo ni aceptación

Código: `modules/tenancy/api/staff_membership_routes.py`,
`NativeStaffInviteBody` y `staff_invite` (`POST /v1/staff/members/native`).
Requiere `identity_authority_id`, `native_identity_id`, `provenance_reference`.
Devuelve membresía `invited`; no dirección, token, envío, aceptación ni expiración.
Crear credenciales, vincular, asignar y activar son pasos separados.

Diseñar invitación durable tenancy con email normalizado, tenant, solicitante,
estado, caducidad, token almacenado por digest y versión. No reutilizar sin más
las invitaciones de Platform Owner: su autoridad es otra. La invitación por sí
sola no concede acceso. Aceptación exige prueba de control y enlace correcto de
identidad; nunca enlazar una identidad existente únicamente por coincidencia de email.
Registrar intención de comunicación/outbox atómicamente, enviar después del commit.
Reenvío y revocación deben invalidar enlaces según política explícita; no hacer
network I/O bajo locks ni repetir ciegamente entregas de resultado desconocido.

Aceptación: nueva/existente identidad, correo repetido, token expirado/revocado,
aceptación repetida/concurrente, invitador suspendido o sin autoridad al aceptar,
tenant incorrecto, proveedor caído y respuesta perdida. Verificar cero grants
prematuros y aislamiento. No usar datos del navegador como ActorContext.

#### A04 · P2 · La lista pierde la paginación

Código: `admin_console/routes_tenant_staff.py:56-64`, `workspace`, y `staff.html`.
Probe ASGI ejecutado: `?after=<uuid>&limit=1` envía solo `{'limit':'1'}`.
Se descarta `next_cursor`; por defecto solo los primeros 50 son alcanzables.

Remediación: reenviar cursor validado, renderizar siguiente/anterior conservando
tenant/filtros. Añadir búsqueda y filtros a la API antes de prometer búsqueda
global en UI. Diferenciar total autorizado de resultados cargados.
Aceptación: 51+ miembros, llegar al último, sin duplicados y sin cambiar tenant.

#### A05 · P2 · Planificar y aplicar son formularios independientes

Código: `routes_tenant_staff.py:95-108`, `staff_detail.html:5`.
Solo se precargan IDs/revisiones; no los grants actuales. Se escribe JSON dos
veces; la vista previa queda colapsada como resultado técnico. PUT reemplaza,
no añade: introducir solo C puede eliminar A/B que el operador quería conservar.

Remediación: un borrador precargado con autoridad visible y catálogo autorizado;
mostrar añadidos/eliminados/bloqueos; aplicar el mismo borrador revisado.
Editar invalida el preview visual; un preview no autoriza el comando.
Aceptación: añadir C conserva A/B, eliminar requiere revisión visible; edición
posterior al plan obliga a revisar de nuevo; conflicto conserva borrador.

#### A06 · P2 · Revisiones y estado obsoletos tras guardar

Código: `routes_tenant_staff.py:147-151`, `staff_detail.html`.
HTMX sustituye solo resultado; estado, grants y expected revisions no cambian.
El segundo cambio desde la misma página usa la revisión anterior.
Remediación: después del éxito leer estado actual por API y refrescar detalle
completo o redirigir. No incrementar números en el cliente por estimación.
Aceptación: dos cambios consecutivos; segundo usa revisión autoritativa nueva.

#### A07 · P2 · Step-up no encuentra formulario y pierde el borrador

Código: `routes_tenant_staff.py:150`, `staff*.html`, `static/admin.js:267-276`.
IDs `staff-plan/authority/status` pertenecen a DIVs, no a formularios. Probe HTML:
formularios sin ID ni `_intent_id`. JS busca `requestSubmit` y termina recargando.
Remediación: IDs separados form/result; reutilizar componente action_form con
intención estable. Prueba de navegador con step-up y mismo cuerpo/clave reenviados.

#### A08 · P2 · Lecturas fallidas conservan formularios de mutación

Código: `routes_tenant_staff.py:93-114`, `staff_detail.html`.
Probe ASGI: upstream 404 produce página 200 con los tres formularios y estado
vacío. No se probó bypass de autorización; la API sigue aplicando controles.
Remediación: separar 401/403/404/503, sin inventar miembro sin permisos; acciones
solo tras lectura válida y descubrimiento autorizado. Probar cada resultado.

#### A09 · P2 · Errores esperables terminan en 500

Código: `routes_tenant_staff.py:34-44,84,135`, `state.runtime_catalog`.
Solo listado comprueba runtime configurado. Falta manejo de MissingOperation,
fallos de red y acción desconocida. Probe POST con CSRF válido y acción
`nonexistent`: 500 por KeyError. Rutas list/get/invite también están en `_OPS`
usado por el despachador de acciones: cerrar la lista a acciones verdaderas.
Remediación: UUIDs tipados, acciones explícitas/enum, 404 desconocida y 503
coherente por configuración/catálogo. Prueba matricial listado/detalle/POST.

#### A10 · P2 · `assignable` no significa que pueda aplicarse

Código: `staff_membership_reader.py:201-211`; baseline `.05.sql:732-745`.
El plan solo prueba techo delegable; el comando además conserva último controlador.
Puede devolver true y fallar determinísticamente sin cambio concurrente.
Remediación: distinguir `within_delegable_ceiling` de `can_apply`; bloqueadores
estructurados (`last_controller`, lifecycle, self-change) cuando sean revelables.
Mantener revalidación. Probar uno/dos controladores y carreras independientes.

#### A11 · P2 · Un permiso de administrar no concede capacidad de delegar

Código: baseline `.05.sql:798`, `replace_staff_authority`: grants nuevos con
`delegable=false`; API recibe solo nombres. Es política aceptada, no bug de
escalada. Un nuevo «administrador» puede tener `staff.manage_authority` y techo vacío.
Remediación: UI diferencie «puede hacer»/«puede conceder»; lectura autorizada de
techo; ceremonia gobernada para promover controlador si el producto la necesita.
No añadir delegable=true indiscriminadamente. Probar imposibilidad de autoescalada.

#### A12 · P2, política preexistente · Suspender un tenant revoca sesiones globales

Código: baseline `.05.sql:1798`, `transition_staff_membership`; `.02.sql:512`,
`revoke_native_sessions`: incrementa epoch de identidad y revoca todas sus sesiones.
Efecto deducido del código; prueba multi-tenant pendiente. No se presenta como
regresión introducida por el panel. Revisar contra contrato de identidad.
Remediación: decidir si corte local depende de membresía/binding y revocación
global exige operación de seguridad de identidad; si se conserva, mostrar alcance
antes de confirmar. Probar identidad en A/B y plataforma, suspender A y observar B.

#### A13 · P2 · Sesión firmada descrita incorrectamente como bearer solo servidor

Código: `admin_console/session.py`, `encode_session`, `encode_value`, settings y
docstrings de auth. `t` está en JSON base64 firmado, sin cifrado. Probe sintético:
se recupera el bearer decodificando la primera sección sin conocer clave.
HttpOnly protege frente a lectura JavaScript, no oculta el contenido al navegador.
No es prueba de robo remoto ni de falsificación de firma.
Remediación: sesión opaca con almacén servidor y TTL/revocación; incluir setup
token. Alternativa cifrada exige contrato explícito y no satisface «solo servidor».
Logout debe limpiar cookie aunque upstream falle; respetar expiración real del
bearer y evitar bucle login→dashboard con cookie vigente/token revocado.
Aceptación: cookie no contiene token; revocar/expirar invalida acceso, logout con
upstream caído limpia sesión; no imprimir tokens reales en pruebas/logs.

#### A14 · P2 · Navegación confunde platform owner con administrador tenant

Código: `tenancy/README.md` (provisioner no pertenece al tenant que crea),
`platform/security/tenant_http.py`, `state.runtime_request`, detalle de organización.
Link existe para toda organización leída pero bearer necesita binding tenant.
Selector nunca debe convertirse en impersonación. Falta un recorrido discoverable
para entrar con autoridad tenant y mostrar nombre/email/último acceso autorizados;
lista actual muestra UUIDs. Lectura global persona→tenants es otra capacidad,
no permiso implícito para inspeccionar cada tenant.
Remediación: API «mis contextos autorizados» + selector; explicar acceso no concedido;
proyección de persona tenant con fuentes verificadas y nulabilidad explícita.
Mantener operación de plataforma distinta de membresía. No inventar MFA, roles,
salud ni métricas de las imágenes si no hay datos reales.

#### A15 · P2 · Evidencia y entorno dejan pasar recorridos rotos

`tests/unit/admin_console/test_tenant_staff.py` solo prueba listado. FakeApi
declara invite en `/v1/staff/members`, pero contrato real usa `/members/native`;
no aporta cuerpos reales ni detalle válido. Nuevo test DB de directorio no figura
en selección explícita `scripts/ci/run_current_product.sh` (staff lifecycle sí).
Verificar todos los selectores CI antes de afirmar cobertura remota; añadirlo al
lane propietario. La base principal está en 0002 y script local intenta otorgar
EXECUTE sobre la función de 0003: falla antes de arrancar si no se migra.

Remediación: OpenAPI real en pruebas del BFF; trayectos y oráculos independientes;
preflight de versión/roles con error accionable. No vaciar/resetear datos locales
para alinear. Scripts de arranque también deben acotar procesos por repo/puerto:
`run_local_panel.ps1` mata cualquier python/cmd cuyo comando contenga `uvicorn`,
incluidos servicios ajenos. Comparte secreto entre cookie, firma de opciones y
fingerprint: separar claves incluso en dev y usar generación criptográfica.

### Contratos propuestos para el siguiente agente (no implementados)

| Operación | Owner / capability propuesta | Semántica y revisión |
|---|---|---|
| POST `/v1/staff/invitations` · `staff_invitation_create` | tenancy / `staff.invite` | Command, Idempotency-Key, email y referencia; devuelve id/estado/expiración/entrega, sin token administrativo reutilizable |
| GET `/v1/staff/invitations` y `/{id}` · `staff_invitation_list/get` | tenancy / lectura explícita a aceptar | Query paginada, filtro estado, tenant ActorContext; 404 ajeno |
| POST `/v1/staff/invitations/{id}:resend` · `staff_invitation_resend` | tenancy / capability de envío a aceptar | Command idempotente, expected_revision; política de token/reintento explícita |
| POST `/v1/staff/invitations/{id}:revoke` · `staff_invitation_revoke` | tenancy / capability de revocación a aceptar | Command idempotente, expected_revision; invalida aceptación, conserva auditoría |
| POST aceptación, ruta final por definir · `staff_invitation_accept` | tenancy / prueba de invitación e identidad | Command de enrollment, no autoridad del modelo/cliente; consumo único, identidad correcta, revalidar alcance concedible |
| GET contextos propios, ruta final por definir | tenancy / contrato self de discovery | Query autenticada y acotada; no requiere adivinar tenant ni lista global administrativa |

Antes de implementar cada operación completar gate docs 15/16: método/recurso,
operationId estable, capability, query/command, idempotencia, revisión,
autoridad/Party, schemas de entrada/salida, errores/retry, garantías afectadas.
No crear MCP paralelo: solo proyectar owner operation si hay consumidor real;
audiencia operator/admin no sustituye autorización. Nombres anteriores son diseño
propuesto; aceptar coherentemente antes de registrarlos.

Invitaciones: READ invitador/tenant/política → PLAN grants/intención → LOCK raíces
de identidad/membresía e invitación en orden canónico → VALIDATE revisión, token,
autoridad actual y unicidad → WRITE hechos/membresía/grants → EMIT outbox. Resolver
el orden exacto con el contrato existente; no introducir locks invertidos. La red
va después del commit. Documentar perdedor concurrente, recuperación y auditoría.

### Secuencia de ejecución y entrega

1. Releer este documento, `git status`, rama/lane, fetch development y rama actual.
   Mantener único lane; no force-push ni descartar commits remotos.
2. Escribir primero prueba falsable A01 y A02. Resolver semántica plan/write en
   tenancy; revisión contractual y migración append-only si cambia SQL.
3. Reparar A04–A10 como un recorrido: contexto → lista → detalle → borrador →
   preview → confirmación → recibo → lectura actualizada. Componente de formulario
   compartido; autorización siempre en owner. Evitar refactor genérico por LOC.
4. Resolver A13 y política A12; no ampliar autoridad para hacer funcionar la UI.
5. Implementar invitación A03 verticalmente: API/durabilidad/entrega/aceptación/UI.
   Tratar crear identidad existente y usuario nuevo, fallos parciales y reenvío.
6. Completar contexto y proyección A11/A14 con datos reales. UX no exige copiar
   todos los widgets de los mockups: priorizar tareas completables sin UUID/JSON.
7. Corregir evidencia/arranque A15. Pruebas focales, `python-quality`, lane
   PostgreSQL current-product y E2E navegador/API mediante infraestructura canónica.
8. Commit y certificación pre-push administrada; CI remoto sobre commit publicado.
   Este handoff no autoriza merge ni declara readiness de producción.

### Matriz mínima de aceptación del journey

| Recorrido | Resultado observable obligatorio |
|---|---|
| Owner sin binding tenant | Explicación y cambio de contexto; ninguna elevación automática |
| Administrador invita correo nuevo | Invitación/entrega trazables; sin acceso antes de aceptación |
| Destinatario acepta | Identidad vinculada al tenant correcto; permisos iniciales exactos |
| Agregar permiso a A/B | A/B conservados, C anunciado y aplicado; sin removals ocultos |
| Timeout después de commit | Estado desconocido visible, replay misma intención, efecto único |
| Segundo cambio en misma visita | Nueva revisión leída, sin conflicto artificial |
| 51+ usuarios | Todos alcanzables por cursor con mismo contexto |
| Lectura 401/403/404/503 | Sin datos ficticios ni botones engañosos; recuperación específica |
| Último controlador / carreras | Bloqueo explicado y garantía transaccional conservada |
| Suspensión en A con identidad A/B | Alcance definido y probado; sin efecto global sorpresivo |

### Referencias externas consultadas

- [Google AIP-158: Pagination](https://google.aip.dev/158): mantener cursor y
  parámetros en navegación; no sustituye el contrato de paginación del repo.
- [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html):
  identificador de sesión cliente y datos de sesión en servidor, expiración y
  revocación. Fundamenta propuesta de sesión opaca; no prueba vulnerabilidad remota.

### Límites y criterio de cierre

Revisión focal, no auditoría exhaustiva de todas las APIs ni prueba visual en
navegador. A01/A10/A12 son evidencia estática con reproducción SQL especificada,
no carreras ejecutadas. A02/A04/A07/A08/A09/A13 tienen probes ejecutados en sus
límites descritos. Las pruebas verdes de publicación no subsanan estos defectos.
Cerrar cada hallazgo con cambio, prueba que fallaba antes y evidencia del entorno;
no marcarlo cerrado por un mock permisivo, un botón visible o un resultado 200.

### Adenda: fallos remotos observados después de publicar

El commit `2be623c8c206899d1caebb456d2f40413d684f90` fue certificado localmente
(`LOCAL_PUSH_CERT PASS`, 180 s) y publicado en origin. `git ls-remote` confirmó
igualdad del SHA local/remoto. Sin embargo, **CI remoto de ese SHA falló**:

- [CI 36627990168](https://github.com/JulioMarte/request-engine/actions/runs/36627990168):
  Python/arquitectura aprobado. PostgreSQL current-product: `1 failed, 34 passed`
  en el primer bloque. Falla `test_security_definers_are_closed_across_all_runtime_schemas`
  (`tests/db/test_runtime_immutable_table_privileges.py:530`): inventario de owners
  no admite las dos funciones nuevas; el primer elemento reportado es
  `request_engine.adopt_platform_owner_v4(): owner=request_platform_control_definer`.
  El aggregate V3 falla por ese prerrequisito, no por una prueba V3 independiente.
- [P7 36627990377](https://github.com/JulioMarte/request-engine/actions/runs/36627990377):
  `1 failed, 147 passed`. Falla
  `test_private_runtime_rechecks_privileges_and_authority[membership]` por
  `RuntimeError: Platform HTTP connection lacks its required command surface`
  en `bootstrap/platform_server.py:190`. La fixture `tests/conftest.py` concede
  lecturas anteriores, pero falta la nueva lectura de organizaciones requerida
  por `_READ`. Corregir la composición de permisos, no eliminar verificación.
- [Docker E2E 36627990148](https://github.com/JulioMarte/request-engine/actions/runs/36627990148):
  control-plane sale con código 3 en smoke, f01-foundation, worker-restart,
  recovery-delivery, platform-configuration y clone-fence. API sí llega a healthy.
  Falta inspeccionar artefactos del contenedor para confirmar causa exacta;
  posible misma desalineación de grants de instalación. No atribuirla como hecho
  sin traceback del contenedor. Coolify contract y observability sí pasan.

Prioridad inicial del siguiente agente: reproducir estos fallos de integración,
revisar mínimos privilegios de ambas funciones y actualizar inventarios exactos
con justificación de owner/ACL/search_path; nunca ampliar globalmente owners
permitidos para silenciar el test. Registrar la lectura nueva en las composiciones
de despliegue/fixtures pertinentes; volver a correr current-product completo,
P7 y E2E. Luego continuar A01–A15. No mezclar errores SQL esperados de pruebas
negativas con fallos de suite: usar resumen pytest y exit status.

Esta adenda solo documenta resultados y remediación. No corrige los fallos remotos.
La rama publicada sigue sin estar lista para merge. La certificación local no
incluye PostgreSQL/E2E y por tanto su PASS no contradice esos resultados.
