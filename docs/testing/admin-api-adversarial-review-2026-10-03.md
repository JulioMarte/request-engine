# Revisión adversarial de administración — 2026-10-03

## Reporte simple (para humanos)

El flujo principal ya tiene una arquitectura razonable: invitar por correo,
aceptar con sesión real, incorporarse sin permisos y asignar permisos después.
No hay motivo para inventar un camino administrativo que escriba directamente
en la base de datos. Sin embargo, las respuestas de fallo todavía confunden al
cliente: un problema del proveedor se presenta como si el usuario debiera cambiar
su petición. Algunos formularios antiguos aceptan campos que luego ignoran, y
aceptar una invitación admite parámetros en la dirección que la vista previa
rechaza. Estos tres comportamientos fueron reproducidos sin usar secretos reales
ni escribir en bases compartidas.

La revisión no prueba una vulnerabilidad de escalamiento, una recepción real de
correo ni seguridad completa frente a cambios concurrentes de permisos. Las
pruebas verdes de transporte no sustituyen las pruebas PostgreSQL de autoridad.
También quedan mejoras de documentación y paginación. No todo hallazgo exige
cambiar rutas, migraciones o política de permisos.

## Reporte técnico (detallado)

### Base y metodología

Base inspeccionada: `e4f65b59eae4fcc032f3b7effc0550c165fe6ee7`; árbol limpio al
inicio. Autoridad normativa: AGENTS raíz/module, docs15/16 y los contratos
`staff-email-invitations`, staff membership/profile/history/contact y self
organization discovery. Primera pasada: solo lectura y pruebas ASGI/Pydantic;
ninguna escritura en PostgreSQL5432/55433, proveedor o correo. Root posteriormente
autorizó corregir R1–R3 en API/tests, conservando límites de autoridad.

Los probes ASGI reutilizaron `_Commands`, `_Resolver`, `_app` de
`tests/unit/test_staff_invitation_http.py`, con excepciones sintéticas y tokens
ficticios. Se imprimieron solo códigos/booleanos/esquemas, no pruebas bearer.
La medición DTO utilizó `model_dump()` para determinar si campos adicionales
eran descartados; no infiere ejecución ni efectos PostgreSQL.

### R1 — P1: error503 da instrucciones de recuperación incorrectas (comprobado)

En `modules/tenancy/api/staff_invitations.py`, create/resend atrapaban cualquier
`RecoveryDeliveryError` y lanzaban `HTTPException(503, ...)`. El mapeo global en
`entrypoints/http/errors.py` producía `code=http_error`, `retryable=false`,
`resolution=fix_request`. Probe con `RecoveryDeliveryUnavailable` confirmó ese
resultado exacto. Cambiar el correo no configura un proveedor; repetir una falla
permanente tampoco ayuda. Las clases Retryable/Unavailable/Permanent ya existen:
no hay razón para borrar su significado en el transporte.

Corrección autorizada: mapeo privado de Tenancy a `ErrorEnvelope`, sin cadenas de
excepción. Retryable:503, código
`staff_invitation_delivery_temporarily_unavailable`, retryable=true,
resolution=`retry_same_request`. Unavailable/Permanent/base desconocida:503,
`staff_invitation_delivery_unavailable`, retryable=false,
resolution=`operator_intervention`. Reintentar significa **misma petición,
Idempotency-Key y revisión**, no pulsar resend para producir otra generación ni
reintentar un SMTP ambiguo. No inventar Retry-After sin conocer un plazo.

Garantías: INV-IDEMPOTENCY-001/INV-WORKER-001/INV-PROVENANCE-001. Falsificadores:
create y resend con cada clase, contenido de excepción privado ausente de toda
respuesta, Envelope503 real, clasificación y no-store; worker unknown no cambia.

### R2 — P2: DTOs antiguos descartan campos desconocidos (comprobado)

`NativeStaffInviteBody`, `StaffAuthorityReplaceBody` y
`StaffMembershipTransitionBody` en `api/staff_membership_routes.py` carecían de
extra=forbid. Probe confirmó que `email`/`organization_id`,
`desired_capabilites` y un campo adicional de transición desaparecían sin error.
No se demostró que un campo ignorado conceda autoridad: ActorContext sigue siendo
la fuente confiable. El problema es admitir contratos aparentemente válidos que
no expresan lo que el cliente cree, especialmente al reemplazar permisos.

Decisión ADAPT preproducción: agregar `ConfigDict(extra="forbid")` a esos tres
DTOs. No se cambia application/domain ni se admiten campos nuevos. No promesa de
compatibilidad externa exige conservar entradas silenciosamente ignoradas.
Prueba requerida: petición válida+campo adicional=>422, comando no invocado;
petición canónica=>mismo resultado e idempotencia/revisión. Conservar
INV-AUTHORITY-001/INV-TENANT-001, sin reexportar tipos internos ni mass assignment.

### R3 — P2: aceptación y vista previa no tienen el mismo contrato cerrado

Probe: POST `:accept?unexpected=ignored` con prueba en body=>200 y owner llamado;
misma query en `:preview`=>400. No prueba bypass de autenticación. Sí permite que
el cliente añada selectores o pruebas a la URL sin rechazo explícito, aumentando
el riesgo de datos en registros de URLs. Rechazar una URL ya recibida no elimina
lo que un proxy haya registrado; sigue siendo obligatorio enviar prueba solo
en body y no registrar URLs con secretos.

Corrección autorizada: rechazar **toda query** en la dependencia subject compartida,
antes del owner, para accept y preview. Mantener rechazo de tenant header,
extra fields, bearer ausente y tokens malformados. Garantías:
INV-TENANT-001/INV-AUTHORITY-001; no token en respuesta/log/prueba de evidencia.

### R4 — P2: OpenAPI no documenta fallos esenciales (comprobado)

OpenAPI del router create inspeccionado anunciaba solo201/422, aunque503 ocurrió
en el mismo probe. Los handlers de staff/invitations pueden devolver401/403,
404 o409 bajo contratos actuales. `add_capability_route` añade policy metadata,
no documentación de errores por sí solo. Clientes generados y el renderer
Advanced reciben información incompleta.

Implementación autorizada junto con R1: declarar `ErrorEnvelope` para los errores
existentes de cada operación; summary/description útiles para staging503,
resend idempotente, proof-in-body y acceptance zero-grants. Mantener IDs estables.
No adoptar RFC9457 unilateralmente: el Envelope actual sigue siendo canónico.
Prueba: schemas referenciados y códigos que realmente se producen, no snapshot
gigante ni errores decorativos que el owner jamás emite.

### R5 — P2: paginación heterogénea y siguiente página vacía (código comprobado)

Invitation/self organizations/staff list usan lookahead. En cambio
platform organizations/native identities/identity bindings/recovery cases indican
next cuando len(rows)==limit sin lookahead. Una última página exactamente llena
ofrece otro enlace que terminará vacío. El resultado no pierde filas ni demuestra
fuga, pero cambia la promesa de `next_*` y añade trabajo al journey.
Además conviven `next_after` y `next_cursor`, todos con UUID públicos, no tokens
opacos vinculados a filtros. Esto es deuda CONTROLLED, no bypass de autoridad.

Instrucciones para siguiente agente: mantener nombres actuales durante esta
pasada; diseñar una política explícita de end-of-collection, solicitar limit+1
dentro del mismo owner y ajustar límites internos de forma controlada. Probar
0/limit-1/limit/limit+1, cambios de filtro, foreign cursor y cursor ausente.
Si se adoptan tokens opacos, versionarlos y vincular tenant/filtros sin convertir
el token en autorización. No crear total counts costosos por defecto.

### R6 — P2: límites/esquemas y semántica de permisos poco autoexplicativos

Create email OpenAPI admite max320, pero el command admite max254 y local-part64,
ASCII mailbox solamente. Un SDK puede considerar válido un correo que el owner
rechaza. Status/delivery_status son strings amplios aunque existen estados cerrados.
PUT authority reemplaza el subconjunto dentro del techo delegable y preserva
grants fuera de él: no es reemplazo irrestricto de todo permiso del usuario.
La documentación de repositorio lo explica; OpenAPI debería hacerlo también.

Siguiente agente: alinear límites de DTO con owner sin duplicar normalización ni
policy. Añadir enums de transporte conscientemente (outputs anteriores deben
seguir válidos). Describir que plan es advisory, can_apply depende de autoridad
actual, Apply revalida revisión/techo/controller y preserva permisos fuera de
techo. No cambiar este invariante para hacer PUT más intuitivo. Probar errores
de email por campo y plan→apply con permisos preservados fuera de techo.

### R7 — P1 hipótesis pendiente: retirada de permiso durante reads

Invitation list hace `_assert_read_authority`, page y statuses en sentencias
separadas dentro de `actor_transaction`. READ COMMITTED no promete el mismo
snapshot. Retirada entre la primera comprobación y las lecturas podría dejar
pasar un resultado de lectura de una petición ya admitida. No se probó este
interleaving ni un fallo de la política ratificada; no etiquetar como explotación.
El batch elimina N+1, no soluciona ni demuestra esta propiedad temporal.

Antes de corregir: acordar el punto de linealización requerido por
INV-AUTHORITY-001. Si cada lectura exige permiso actual en la misma sentencia,
incorporar el predicado al Query owner, sin SQL Communications desde Tenancy.
No usar REPEATABLE READ como sustituto de autoridad fresca. Prueba con dos
conexiones/sincronización determinista y retirada real bajo roles restringidos;
no sleeps ni ActorContext falso. No tocar migración0012 de otro agente.

### Recorrido recomendado, sin nuevos caminos administrativos

1. Login native canónico; `/v1/me/organizations` descubre membresías sin conceder
   permisos. Seleccionar organización es contexto, no autorización.
2. Consultar overview y staff con status/search/paginación server-side; distinguir
   persona global, membership tenant-local y perfil/display label.
3. Invitar correo por API Tenancy. Mostrar pending/unknown/failed separado de
   accepted; SMTP accepted no significa inbox o lectura.
4. Recipient preview y accept con bearer native+body proof, sin tenant selector.
   Acceptance crea cero grants; no redirigir automáticamente a staff protegido.
5. Admin abrir membership devuelto, revisar perfil/historial y plan→apply con
   revisión+provenance+misma idempotency. Nunca un formulario role=admin que
   fabrique grants.
6. Recuperación global de identidad solo en control-plane permitido. No confundir
   deshabilitar identidad global con suspender membership en una organización.
   Issue202 requiere explicar consulta de caso/delivery posterior, no prometer
   entrega instantánea ni reintentar envío ambiguo.

### Guías oficiales consultadas y aplicación selectiva

OWASP exige autorización por objeto y propiedades y advierte contra entrada/
salida excesiva; esto justifica pruebas foreign target y contratos cerrados, no
afirmar que cada campo ignorado ya sea una vulnerabilidad.
[API1](https://api-security.owasp.org/editions/2023/en/0xa1-broken-object-level-authorization/),
[API3](https://api-security.owasp.org/editions/2023/en/0xa3-broken-object-property-level-authorization/).

Google recomienda cursores opacos, parámetros consistentes y tokens que nunca
autorizan recursos. Su request identification orienta retries sin duplicar
efectos. Request Engine conserva Idempotency-Key y su garantía ratificada; no
copiar request_id como segunda autoridad.
[AIP158](https://google.aip.dev/158), [AIP155](https://google.aip.dev/155).

Microsoft recomienda recursos claros, respuestas/errores documentados y consulta
de progreso para tareas asíncronas. Se aplica al staging/delivery y issue202;
no convierte toda mutación en202 ni obliga a cambiar el Envelope existente.
[API design](https://learn.microsoft.com/en-us/azure/architecture/best-practices/api-design),
[async request-reply](https://learn.microsoft.com/en-us/azure/architecture/patterns/asynchronous-request-reply).
Consultadas2026-10-03; no citas literales extensas.

### Evidencia ejecutada y alcance

- DTO probe Pydantic: tres clases descartaban extras=true.
- ASGI probe: accept query200/owner1, preview query400, staging unavailable503
  con http_error/fix_request/retryablefalse; create responses201/422, email max320.
- `uv run pytest tests/modules/tenancy/test_staff_membership_admin_router.py
  tests/modules/tenancy/test_staff_profile_http.py tests/modules/tenancy/test_staff_contact_router.py
  tests/modules/tenancy/test_staff_history_http.py tests/modules/tenancy/test_staff_invitation_list_batch.py
  -q --tb=short`:44 PASS.
- `uv run pytest tests/unit/test_staff_invitation_http.py
  tests/unit/admin_console/test_staff_invitations.py
  tests/modules/tenancy/test_platform_organization_reads.py -q --tb=short`:40 PASS.

No canonical Python lane, PostgreSQL/crypto/concurrencia, navegador autenticado,
entrega humana, production ACL o GitHub exact-head CI fueron certificados por
esta primera pasada. Estos resultados corresponden a la base, no a correcciones
posteriores. No commit/push de este agente.

### Corrección posterior autorizada (árbol de trabajo, sin publicación)

R1/R2/R3/R4 se implementaron en `api/staff_invitations.py`,
`api/staff_membership_routes.py`, `tests/unit/test_staff_invitation_http.py` y
`tests/modules/tenancy/test_staff_command_input_contract.py`. La descripción de
errores ahora es independiente del proveedor y contiene solo códigos sanitizados.
Revoke y accept también capturan `RecoveryDeliveryError`, porque la pérdida de
configuración del recorder podía escapar como500; **no** prometen retry automático
para esos comandos, ni siquiera ante una clase técnica Retryable. Create/resend
conservan retry_same_request solo para la clase explícita Retryable.

Pruebas focales ejecutadas después del cambio:37 PASS; Ruff y Pyright de los cuatro
archivos PASS. Incluyen cuatro comandos por cuatro clases técnicas, ausencia de
texto privado, schemas503 reales, no-store, query rejection antes del owner,
extra fields422 antes del command y body canónico que conserva Idempotency-Key.
Ninguna mutación owner, migración, grant o worker se cambió. Las pruebas PostgreSQL
de autoridad/efectos siguen pendientes de la coordinación de la base aislada y
no están implícitas en estas pruebas HTTP. R5–R7 permanecen pendientes; no se
certifica la publicación ni el canonical lane completo.

Validación ampliada posterior:128 PASS combinando estos archivos:
`test_staff_membership_admin_router.py`, `test_staff_profile_http.py`,
`test_staff_contact_router.py`, `test_staff_history_http.py`,
`test_staff_invitation_list_batch.py`, `test_staff_command_input_contract.py`,
`tests/unit/test_staff_invitation_http.py`,
`tests/unit/admin_console/test_staff_invitations.py`,
`test_platform_organization_reads.py` y las pruebas arquitectónicas
`test_api_operation_pattern.py`, `test_operational_api_capability_contract.py`,
`test_dependency_guardrail_conformance.py`. Comando: `uv run pytest <estos paths>
-q --tb=short` (los tests `test_staff_*` sin prefijo están en
`tests/modules/tenancy/`; los arquitectónicos en `tests/architecture/`). Ruff y
Pyright focales volvieron a pasar después de la última edición.

Esta prueba incluye el adaptador HTTP y la proyección BFF, no la ejecución
PostgreSQL de los comandos. No se debe confundir arquitectura/contrato HTTP con
prueba de RLS, rollback, revocación concurrente o criptografía. La base aislada
fue cedida al agente de recovery/WebAuthn y después al inventario de cleanup;
este agente no ejecutó fixtures de DB ni se conectó a5432 en esta pasada.
