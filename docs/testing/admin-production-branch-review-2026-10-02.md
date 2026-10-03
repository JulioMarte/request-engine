# Revisión semántica adversarial del branch — c696

## Reporte simple (para humanos)

Revisión parcial y explícita de los 88 candidatos anteriores al último commit. No están todos aprobados. Se identificó un riesgo de falsificación del formulario de acceso y configuración inicial, una continuación falsa al terminar exactamente una página de personal y dos riesgos de robustez/redacción que requieren pruebas adicionales. La revisión inicial no ejecutó pruebas nuevas; el anexo posterior sí demuestra que la prueba de acceso rechaza el código viejo y pasa después de corregirlo. No demuestra una fuga de autoridad ni un fallo de PostgreSQL.

La seguridad de los formularios se entregó inmediatamente a root y recibió autorización separada para corrección. Las disposiciones describen c696; el anexo registra por separado la corrección posterior y su prueba. Los candidatos sin lectura completa de sus dependencias conservan INSUFFICIENT_CONTEXT. No se propone dividir archivos solo porque son grandes.

## Reporte técnico (detallado)

Revisión SHA exacto `c696fdddc6c83dd9e572b26db082f184d19f88f9`. 108 paquetes quality-evidence/v2 suministrados y validados por root; excluidos 20 candidatos cuyos archivos cambiaron en c696 frente a c696^, revisados por root. Aquí se conserva disposition de los otros 88: {"INSUFFICIENT_CONTEXT":64,"HEALTHY_AS_IS":16,"REVIEW_CONCERN":8}. `human_verdict: null` para todos. La prueba adversarial posterior no reescribe los paquetes ni convierte esta revisión en certificación de otro SHA.

Se abrió inventario y campos source/tested/base/mode/scope/trigger/facts/architecture de cada paquete. Los 88 source_head_sha y tested_sha coinciden con c696. Todos incluyen resultados pass para baseline, architecture-diff, scan, lint, format, type, architecture, unit y module. Son hechos del paquete suministrado: no reejecuté esas suites durante esta revisión, no sustituyen prueba de explotación ni la revisión semántica, y no permiten inferir resultado PostgreSQL/browser/provider. Facts exactos de cada candidato aparecen abajo; no se modificaron mediciones.

Contexto normativo leído: AGENTS y mapas ya leídos para esta tarea, protocolo SRP y playbook completos; Tenancy README exacto, Communications README exacto, admin console README exacto, contrato staff-email-invitations exacto (lectura previa completa más cambios actuales), contratos previos docs15/16, DB/access, garantías y arquitectura. Fuente obtenida con `git show c696:path` para independencia del working tree. No código/commit/push en esta fase.

### G1 — invitación y entrega

Unidades completas: tenancy staff_invitation_commands.py y api/staff_invitations.py; communications worker y DB recorder staff_invitation_delivery.py; BFF routes_staff_invitations.py. Se inspeccionó idempotency/postgres.py como dependencia directa y sus operaciones actuales; sin lectura exhaustiva de toda función SQL de 0009/0010.

Evidencia semántica: stage precede locks; administración revalida lock_staff_invitation_admin antes de replay; acceptance/preview usan prueba y sesión real, no actor/tenant fabricados; DTO no devuelve proof/ref; delivery prepara bajo fence, libera transacción antes provider y finaliza sin sobrescribir cancelled; UNKNOWN reconcilia y no envía ciegamente. Unidades grandes son fases cohesivas de una intención, no responsabilidades arbitrarias. HEALTHY_AS_IS significa sin refactor justificado por el sensor, no certificación de SQL o carreras.

REVIEW_CONCERN para commands: list realiza una consulta delivery-status por invitación (hasta 101), además de check + list; degrada navegación con latencia por fila. Confianza medium, no medición de rendimiento. Contraargumento: límite pequeño, adaptador recorder conserva ownership y no hay evidencia de SLA incumplido. Acción: medir llamadas/latencia con 100 filas; si significativo, contrato outbound batch de status explícito, sin SQL communications desde Tenancy. No crear helper genérico ni romper transaction para bajar LOC. Verificar representación/replay y aislamiento si se cambia.

### G2 — acceso y configuración inicial

Unidades completas routes_auth.py y routes_setup.py; dependencia app.py exacta leída. Sin guard de origen central en c696. Login password POST no valida nonce ni Origin y fija sesión nueva. Logout y step-up cookie-backed tampoco verifican CSRF; setup recovery-codes consume cookie sin CSRF. SameSite no impide que un POST anónimo establezca cookie nueva: login-CSRF puede colocar cuenta atacante en navegador víctima. Confianza high en ausencia de defensa en fuente; explotación real en Chrome aún NO ejecutada. Avisado inmediatamente a root; no hallazgo determinista fabricado.

Contraargumento: same-origin JS, CSP y cookies limitan lectura de respuesta/cross-origin JSON, y WebAuthn sí valida origin criptográfico; esto no protege POST HTML login y tampoco sustituye anti-CSRF del BFF. Acción antes publicación: política Origin fail-closed central para mutaciones de navegador, o nonce anónimo firmado y tokens en cada ruta cookie-backed. Mantener APIs owner canónicas, no solución exclusivamente JS. Prueba ASGI missing/null/cross-origin antes upstream y antes Set-Cookie; misma-origen funcional; Chrome adversarial complementario. No extraer routers solo para reducir C901.

### G3 — catálogo y ejecución BFF

Unidades completas catalog.py, state.py, execution.py, forms.py y routes_operations.py; dependencia idempotency/postgres.py. Catálogo procede OpenAPI y no autoriza; state conserva separación runtime/control; executor usa mismo pipeline y preserva intent para timeout/HTTPError ambiguo. Grande por DTO/mapa y operaciones lineales; HEALTHY_AS_IS sin extractores ceremoniales.

forms REVIEW_CONCERN medium: render_path sustituye parámetros sin percent-encoding; parámetros con /, ?, # o .. pueden cambiar el recurso/consulta solicitado en lugar de representar un único segmento. Fuente comprobada, alcance exploit no probado y autoridad owner aún debe impedir elevación. Contraargumento: muchos parámetros UUID validan en owner y usuarios técnicos pueden introducir entradas deliberadas. Acción: codificar valores de cada segmento con quote(safe=''), probar slash/query/fragment traversal manteniendo custom method :suffix, no aceptar URLs completas. Reprobar executor y workspaces. No mezclar política de negocio ni crear otra API.

### G4 — administración de membresías

Unidades completas membership reader, commands, HTTP reads y HTTP routes, Tenancy README exacto. Reader consultas revalidan current HUMAN grant y tenant en mismo snapshot y planner filtra ceiling; rutas HTTP conservan tipos/revisiones. Declaración de rutas anidadas explica C901 sin refactor obligatorio.

HTTP reads REVIEW_CONCERN high: next_cursor cuando len(rows)==limit sin lookahead crea continuación falsa en última página exactamente llena. Acción: fetch limit+1 y recortar; probar 0, limit-1, limit, limit+1 con status/search y ausencia side effects. Contraargumento: página extra vacía no expone información, pero contradice journey claro. Reader HEALTHY_AS_IS porque política/consulta permanece local; coordinación de mejora corresponde HTTP+reader.

Commands INSUFFICIENT_CONTEXT: leído completo; invite/authority/status replay retorna antes de funciones owner de validación, mientras profile llama lock incluso en replay. Falta inspeccionar acquire_idempotency SQL y contratos vigentes de revocación/replay para concluir si stale ActorContext puede observar replay tras retirada. No afirmar vulnerabilidad ya probada. Enriquecer con SQL completo y prueba restricted runtime de replay tras revoke; no agregar consulta sin resolver orden lock/idempotency.

### G5 — telemetría y SMTP

Unidades completas observability.py y SMTP delivery channel; callers state/app examinados. SMTP distingue no-transmission retry de incertidumbre, usa contexto TLS verificador y valida un solo mailbox; HEALTHY_AS_IS medium, no prueba de inbox ni exactamente-once.

Observability REVIEW_CONCERN medium: redact cubre claves estructuradas, pero JsonFormatter agrega formatException sin redacción y ErrorTracker acepta message/detail libres; app utiliza str(exc) y trace. Existe riesgo de excepción con secreto en texto, no se demostró una excepción production concreta que lo filtre. Contraargumento: requests no se loguean y fixtures normales no incluyen secretos; debug es explícito. Acción: prueba canaria de excepción conteniendo credencial y garantizar logs/diagnostics no la devuelven; registrar tipo/código seguro por defecto y limitar trace. No prometer redacción perfecta por regex ni ocultar todo diagnóstico.

### G6 — revisión pendiente, no aprobación tácita

Cada INSUFFICIENT_CONTEXT restante requiere lectura completa de archivo exacto, diff contra base del paquete, owner README y dependencies/callers/tests relevantes. Inventario y hechos fueron revisados pero no basta para disposition responsable; pruebas grandes no se aprueban por cantidad de asserts y migraciones no se aprueban por tener wrappers. Falta especialmente unidades completas SQL 0002–0011, webauthn/session/materialization y sus pruebas independientes/privilegios. Confianza low. Contraargumento: paquetes muestran suites verdes y algunos archivos son declarativos; eso no sustituye contexto semántico. Acción: continuar por owner/grupo y conservar estos IDs. No partir, suprimir ni widen allowlists. Verificación requerida según garantía: python-quality, PG18 restricted runtime/concurrencia y browser cuando corresponda. Esta revisión parcial no bloquea por sensor ni certifica completitud.

## Disposiciones explícitas

### Anexo posterior autorizado — corrección G2 en working tree

Después de la revisión, root autorizó una corrección separada. `app.py` ahora
requiere Origin válido único y mismo scheme/host/puerto en todos los métodos
unsafe, antes de upstream o Set-Cookie. Conserva CSRF existente, normaliza
puertos por defecto, no consume Forwarded/X-Forwarded de clientes. README explica
ingress HTTPS y trust del ASGI server. No modifica las APIs bearer canónicas.
Clientes de pruebas existentes reciben Origin explícito, sin monkeypatch global.

Falsificación ASGI en proceso independiente: se cargó app.py exacto c696 con
`git show` y `exec` en memoria (sin modificar working tree), y se ejecutó
`test_origin_boundary.py -k 'unsafe_origin_never and attacker' --maxfail=1`:
1 failed, 77 deselected; el código viejo devolvió 303 y llamó al owner login en
lugar de 403. La variante sin Origin también falla contra c696. No es un exploit
Chrome y no se utiliza como prueba de WebAuthn o PostgreSQL.

Código actual: `uv run pytest tests/unit/admin_console -q`: 238 passed en 34.38s;
dedicated origin suite: 84 passed en 5.77s. Ruff check + format check app/BFF
conformes; Pyright app/dedicated test: 0 errors, 0 warnings. `git diff --check`
exit 0. Estado PENDING_REPROOF global/exact-head: root ejecutará canonical lane
y emitirá nuevo SHA/evidence; este anexo no certifica ese resultado. No commit/push.

Propiedad protegida por trigger: FSIZE cohesión/localidad; CPLX complejidad real; NAV valor del límite e indirection. Razonamiento, contraargumentos y acción se vinculan al grupo; arquitectura de todos los paquetes es pass según evidencia suministrada, sin waiver. Los INS UFFICIENT_CONTEXT se escriben con la forma válida INSUFFICIENT_CONTEXT.

| Candidate ID | Unidad exacta | Trigger y facts deterministas | Disposition | Confidence | Grupo |
|---|---|---|---|---|---|
| QR-01d51ced7873 | `src/request_engine/entrypoints/http/app.py` / app.py | QR-FSIZE-001; effective_file_loc=320 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-05d997bf14a8 | `src/request_engine/bootstrap/server.py` / create_app | QR-CPLX-001; function_mccabe=21 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-096ab2420b59 | `migrations/versions/0007_controller_read_scope.py` / 0007_controller_read_scope.py | QR-NAV-001; one_call_forwarder_count=2;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-0bd72e799da5 | `migrations/versions/0006_staff_controller_continuity.py` / 0006_staff_controller_continuity.py | QR-FSIZE-001; effective_file_loc=413 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-0be6ef6c3521 | `tests/unit/admin_console/test_my_organizations.py` / test_my_organizations.py | QR-FSIZE-001; effective_file_loc=155 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-0ea2f424188a | `tests/db/test_native_identity_actor_runtime.py` / test_native_identity_actor_runtime.py | QR-FSIZE-001; effective_file_loc=255 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-10a536f65e8f | `migrations/versions/0005_staff_authority_ceiling_replace.py` / 0005_staff_authority_ceiling_replace.py | QR-FSIZE-001; effective_file_loc=390 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-148b255758ba | `src/request_engine/modules/communications/adapters/worker/staff_invitation_delivery.py` / staff_invitation_delivery.py | QR-FSIZE-001; effective_file_loc=178 | HEALTHY_AS_IS | medium | G1 |
| QR-184dc15ac334 | `migrations/versions/0011_staff_member_profiles.py` / 0011_staff_member_profiles.py | QR-NAV-001; one_call_forwarder_count=2;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-19a538f504f0 | `src/request_engine/modules/tenancy/api/staff_membership_routes.py` / add_staff_membership_routes | QR-CPLX-001; function_mccabe=11 | HEALTHY_AS_IS | medium | G4 |
| QR-1bb94b773ab5 | `src/request_engine/modules/tenancy/api/staff_membership_routes.py` / staff_membership_routes.py | QR-FSIZE-001; effective_file_loc=182 | HEALTHY_AS_IS | medium | G4 |
| QR-1d259decc8d6 | `tests/db/test_platform_organization_directory.py` / test_platform_organization_directory.py | QR-FSIZE-001; effective_file_loc=130 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-27273c85d9be | `tests/db/test_staff_member_profiles.py` / test_staff_member_profiles.py | QR-FSIZE-001; effective_file_loc=270 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-28dfa4057b23 | `src/request_engine/bootstrap/admin_console_server.py` / admin_console_server.py | QR-NAV-001; one_call_forwarder_count=1;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-294f5cf0b8ad | `src/request_engine/entrypoints/http/module_composition.py` / module_composition.py | QR-FSIZE-001; effective_file_loc=156 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-2e5456726d27 | `src/request_engine/bootstrap/recovery_delivery.py` / recovery_delivery.py | QR-FSIZE-001; effective_file_loc=238 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-3309e864307a | `scripts/dev/mock_control_plane.py` / mock_control_plane.py | QR-FSIZE-001; effective_file_loc=303 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-3723c466e26a | `tests/modules/tenancy/test_staff_membership_admin_router.py` / test_staff_membership_admin_router.py | QR-FSIZE-001; effective_file_loc=271 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-3750562a1df9 | `src/request_engine/entrypoints/http/admin_console/routes_auth.py` / install_auth_routes | QR-CPLX-001; function_mccabe=20 | REVIEW_CONCERN | high | G2 |
| QR-3cc03636f19e | `migrations/versions/0009_staff_email_invitations.py` / 0009_staff_email_invitations.py | QR-NAV-001; one_call_forwarder_count=2;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-3f2fca270f15 | `tests/db/test_staff_email_invitations.py` / test_staff_email_invitations.py | QR-FSIZE-001; effective_file_loc=698 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-41d91025f801 | `migrations/versions/0008_self_organization_discovery.py` / 0008_self_organization_discovery.py | QR-NAV-001; one_call_forwarder_count=2;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-473435684b01 | `src/request_engine/entrypoints/http/admin_console/routes_setup.py` / install_setup_routes | QR-CPLX-001; function_mccabe=24 | REVIEW_CONCERN | high | G2 |
| QR-4a45d2065f82 | `src/request_engine/modules/tenancy/application/errors.py` / errors.py | QR-FSIZE-001; effective_file_loc=201 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-4c3da0361943 | `tests/e2e/test_native_webauthn_login_http.py` / test_native_webauthn_login_http.py | QR-FSIZE-001; effective_file_loc=959 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-50710ae284b9 | `migrations/versions/0006_staff_controller_continuity.py` / 0006_staff_controller_continuity.py | QR-NAV-001; one_call_forwarder_count=2;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-525234971ab7 | `src/request_engine/bootstrap/platform_server.py` / create_app | QR-CPLX-001; function_mccabe=11 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-5310ea21acea | `src/request_engine/entrypoints/http/admin_console/routes_auth.py` / routes_auth.py | QR-FSIZE-001; effective_file_loc=186 | REVIEW_CONCERN | high | G2 |
| QR-58f0bf8dcd7f | `tests/e2e/http_surface.py` / http_surface.py | QR-FSIZE-001; effective_file_loc=328 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-5bd9fba198ac | `src/request_engine/modules/tenancy/adapters/db/staff_membership_commands.py` / staff_membership_commands.py | QR-FSIZE-001; effective_file_loc=404 | INSUFFICIENT_CONTEXT | low | G4 |
| QR-5cde0d167a45 | `src/request_engine/modules/communications/adapters/db/staff_invitation_delivery.py` / staff_invitation_delivery.py | QR-FSIZE-001; effective_file_loc=132 | HEALTHY_AS_IS | medium | G1 |
| QR-612a9f0207a5 | `tests/db/test_instance_claim.py` / test_instance_claim.py | QR-FSIZE-001; effective_file_loc=439 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-62453f9c185b | `src/request_engine/entrypoints/http/admin_console/routes_staff_invitations.py` / install_staff_invitation_routes | QR-CPLX-001; function_mccabe=48 | HEALTHY_AS_IS | medium | G1 |
| QR-63fc30cc8cf1 | `src/request_engine/entrypoints/http/admin_console/execution.py` / execution.py | QR-FSIZE-001; effective_file_loc=185 | HEALTHY_AS_IS | medium | G3 |
| QR-647d38d9ef71 | `src/request_engine/bootstrap/server.py` / server.py | QR-FSIZE-001; effective_file_loc=207 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-65ab86489c88 | `src/request_engine/entrypoints/http/admin_console/routes_resources.py` / install_resource_routes | QR-CPLX-001; function_mccabe=73 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-66479ffb0522 | `tests/unit/admin_console/test_resources.py` / request | QR-CPLX-001; function_mccabe=13 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-66a887760616 | `src/request_engine/entrypoints/http/platform_control_app.py` / platform_control_app.py | QR-FSIZE-001; effective_file_loc=189 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-6e4284cad14e | `src/request_engine/platform/db/webauthn_store.py` / webauthn_store.py | QR-FSIZE-001; effective_file_loc=386 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-70aa76dad464 | `tests/db/test_platform_definer_topology.py` / test_platform_definer_topology.py | QR-FSIZE-001; effective_file_loc=314 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-7512f46914ac | `tests/db/test_staff_membership_lifecycle.py` / test_staff_membership_lifecycle.py | QR-FSIZE-001; effective_file_loc=1398 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-764f3c852353 | `src/request_engine/entrypoints/http/native_auth.py` / create_native_auth_router | QR-CPLX-001; function_mccabe=53 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-7ce31b8ba060 | `tests/db/test_identity_topology_gate.py` / test_identity_topology_gate.py | QR-FSIZE-001; effective_file_loc=560 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-7e6c661ddf65 | `tests/db/test_webauthn_persistence.py` / test_webauthn_persistence.py | QR-FSIZE-001; effective_file_loc=659 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-801b9956bbae | `tests/unit/test_staff_invitation_http.py` / test_staff_invitation_http.py | QR-FSIZE-001; effective_file_loc=187 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-805e1172be81 | `src/request_engine/platform/security/capability_registry_identity_authority.py` / capability_registry_identity_authority.py | QR-FSIZE-001; effective_file_loc=306 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-8199a6a5a73e | `src/request_engine/entrypoints/http/admin_console/routes_operations.py` / install_operation_routes | QR-CPLX-001; function_mccabe=22 | HEALTHY_AS_IS | medium | G3 |
| QR-84e07bb86eee | `src/request_engine/entrypoints/http/admin_console/resources.py` / resources.py | QR-FSIZE-001; effective_file_loc=327 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-8758e2eaf2e9 | `src/request_engine/entrypoints/http/admin_console/forms.py` / forms.py | QR-FSIZE-001; effective_file_loc=169 | REVIEW_CONCERN | medium | G3 |
| QR-89120c748dbc | `tests/e2e/test_public_surface_contract.py` / test_public_surface_contract.py | QR-FSIZE-001; effective_file_loc=134 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-8a344ac02e33 | `migrations/versions/0009_staff_email_invitations.py` / 0009_staff_email_invitations.py | QR-FSIZE-001; effective_file_loc=351 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-8b9e2a4e3808 | `src/request_engine/modules/tenancy/api/platform_organization_reads.py` / platform_organization_reads.py | QR-FSIZE-001; effective_file_loc=156 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-8c40d8faa546 | `src/request_engine/entrypoints/http/native_runtime.py` / native_runtime.py | QR-FSIZE-001; effective_file_loc=149 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-93bd1bd0b60b | `src/request_engine/entrypoints/http/native_auth.py` / native_auth.py | QR-FSIZE-001; effective_file_loc=1040 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-980f27abe646 | `migrations/versions/0003_platform_org_directory.py` / 0003_platform_org_directory.py | QR-FSIZE-001; effective_file_loc=181 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-9d20913e347d | `src/request_engine/modules/tenancy/api/staff_invitations.py` / staff_invitations.py | QR-FSIZE-001; effective_file_loc=270 | HEALTHY_AS_IS | medium | G1 |
| QR-a0ebe78bfa1a | `src/request_engine/entrypoints/http/admin_console/routes_operations.py` / routes_operations.py | QR-FSIZE-001; effective_file_loc=413 | HEALTHY_AS_IS | medium | G3 |
| QR-a1f1f29ef599 | `src/request_engine/bootstrap/reference_worker_factory.py` / reference_worker_factory.py | QR-FSIZE-001; effective_file_loc=193 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-a2d73be250d9 | `src/request_engine/modules/tenancy/adapters/db/staff_membership_reader.py` / staff_membership_reader.py | QR-FSIZE-001; effective_file_loc=377 | HEALTHY_AS_IS | medium | G4 |
| QR-a8d753673d5e | `migrations/versions/0002_discoverable_webauthn_login.py` / 0002_discoverable_webauthn_login.py | QR-FSIZE-001; effective_file_loc=322 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-abac2338afc9 | `src/request_engine/entrypoints/http/admin_console/observability.py` / observability.py | QR-FSIZE-001; effective_file_loc=138 | REVIEW_CONCERN | medium | G5 |
| QR-ac6618dcb2a2 | `src/request_engine/entrypoints/http/admin_console/routes_staff_invitations.py` / routes_staff_invitations.py | QR-FSIZE-001; effective_file_loc=326 | HEALTHY_AS_IS | medium | G1 |
| QR-ac9ac13d425b | `src/request_engine/modules/tenancy/api/staff_invitations.py` / create_staff_invitation_router | QR-CPLX-001; function_mccabe=15 | HEALTHY_AS_IS | medium | G1 |
| QR-ae5ac6acc847 | `tests/e2e/test_instance_setup_http.py` / test_instance_setup_http.py | QR-FSIZE-001; effective_file_loc=227 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-b1012d7ac301 | `src/request_engine/entrypoints/http/admin_console/catalog.py` / catalog.py | QR-FSIZE-001; effective_file_loc=222 | HEALTHY_AS_IS | medium | G3 |
| QR-b14901988a74 | `migrations/versions/0010_invitation_topology_gate.py` / 0010_invitation_topology_gate.py | QR-NAV-001; one_call_forwarder_count=3;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-b3cf1ae40f2c | `tests/db/test_staff_invitation_delivery.py` / test_staff_invitation_delivery.py | QR-FSIZE-001; effective_file_loc=312 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-bd93c27b9ee3 | `src/request_engine/entrypoints/http/admin_console/routes_resources.py` / routes_resources.py | QR-FSIZE-001; effective_file_loc=818 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-c53c0e65cc91 | `tests/unit/admin_console/test_staff_invitations.py` / test_staff_invitations.py | QR-FSIZE-001; effective_file_loc=377 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-c5ad3eaaec4b | `tests/modules/tenancy/test_platform_organization_reads.py` / test_platform_organization_reads.py | QR-FSIZE-001; effective_file_loc=162 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-cb38a83be67f | `tests/db/test_platform_root_bootstrap_consume.py` / test_platform_root_bootstrap_consume.py | QR-FSIZE-001; effective_file_loc=201 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-cc29a55e129c | `src/request_engine/entrypoints/http/admin_console/routes_setup.py` / routes_setup.py | QR-FSIZE-001; effective_file_loc=211 | REVIEW_CONCERN | high | G2 |
| QR-d125746e7280 | `src/request_engine/modules/tenancy/api/staff_membership_reads.py` / staff_membership_reads.py | QR-FSIZE-001; effective_file_loc=204 | REVIEW_CONCERN | high | G4 |
| QR-d994de76754d | `src/request_engine/modules/tenancy/adapters/db/staff_invitation_commands.py` / staff_invitation_commands.py | QR-FSIZE-001; effective_file_loc=580 | REVIEW_CONCERN | medium | G1 |
| QR-db064e7a6e43 | `tests/unit/admin_console/conftest.py` / conftest.py | QR-NAV-001; one_call_forwarder_count=1;reexport_only_module=False | INSUFFICIENT_CONTEXT | low | G6 |
| QR-df32fa0be6bf | `tests/unit/admin_console/test_resources.py` / test_resources.py | QR-FSIZE-001; effective_file_loc=693 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e02a2a734155 | `tests/db/app_function_surface.py` / app_function_surface.py | QR-FSIZE-001; effective_file_loc=172 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e16809fb76a1 | `tests/unit/platform/secrets/test_smtp_delivery_channel.py` / test_smtp_delivery_channel.py | QR-FSIZE-001; effective_file_loc=267 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e2cd30800a26 | `src/request_engine/platform/security/native_webauthn_auth.py` / native_webauthn_auth.py | QR-FSIZE-001; effective_file_loc=487 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e2e186cc862f | `src/request_engine/entrypoints/http/admin_console/routes_staff_invitations.py` / workspace | QR-CPLX-001; function_mccabe=13 | HEALTHY_AS_IS | medium | G1 |
| QR-e497fe18745b | `tests/conftest.py` / conftest.py | QR-FSIZE-001; effective_file_loc=202 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e73d5acbdedc | `src/request_engine/platform/secrets/smtp_delivery_channel.py` / smtp_delivery_channel.py | QR-FSIZE-001; effective_file_loc=223 | HEALTHY_AS_IS | medium | G5 |
| QR-e7456de9c500 | `tests/db/test_runtime_immutable_table_privileges.py` / test_runtime_immutable_table_privileges.py | QR-FSIZE-001; effective_file_loc=523 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e9bc4698bacf | `src/request_engine/bootstrap/worker.py` / worker.py | QR-FSIZE-001; effective_file_loc=132 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-e9e1fbb6e982 | `src/request_engine/entrypoints/http/admin_console/state.py` / state.py | QR-FSIZE-001; effective_file_loc=249 | HEALTHY_AS_IS | medium | G3 |
| QR-eed2e0df3c1c | `tests/db/test_self_organization_discovery.py` / test_self_organization_discovery.py | QR-FSIZE-001; effective_file_loc=183 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-f3db92bae235 | `tests/unit/test_self_organizations_http.py` / test_self_organizations_http.py | QR-FSIZE-001; effective_file_loc=124 | INSUFFICIENT_CONTEXT | low | G6 |
| QR-ff49fe31057b | `src/request_engine/bootstrap/platform_server.py` / platform_server.py | QR-FSIZE-001; effective_file_loc=347 | INSUFFICIENT_CONTEXT | low | G6 |
