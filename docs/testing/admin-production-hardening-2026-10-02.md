# Admin production hardening — 2026-10-02

## Reporte simple (para humanos)

Esta continuación añade un historial administrativo de cada miembro, corrige una
comprobación que podía declarar disponible el panel con su API de usuarios caída
y verifica que las pruebas temporales del almacén de secretos tengan vencimiento
real. El historial no concede acceso adicional ni revela datos privados.

No es una certificación de producción. Chrome no está disponible en la conexión
de herramientas. Faltan la aceptación de correo real y del entorno de despliegue,
la política operativa de destrucción y backups de secretos, y las métricas de
identidad cuyo contrato aún requiere definición. No se borraron datos del usuario.

## Reporte técnico (detallado)

### Cambios de sistema

- Tenancy: GET `/v1/staff/members/{membership_id}/history`, operationId
  `staff_history_list`, HUMAN `staff.read` vigente, Query sin idempotencia ni
  mutaciones. Target/cursor/autoridad comparten snapshot SQL con RLS tenant.
  Orden `(created_at,id) DESC`, `limit+1`, cursor solo del mismo miembro/tenant.
  Proyección cerrada de cuatro comandos, sin payload/provenance/contactos.
  DTO, aplicación y adaptador permanecen separados. No nueva migración.
- BFF: `routes_tenant_staff.py` y `templates/resources/staff_history.html`;
  página separada, solo API runtime, credencial de sesión y selector tenant,
  errores sanitizados, navegación newest/older y enlace desde el detalle.
  El diseño mantiene la consulta fuera de los formularios de mutación y evita
  inventar actividad de login o entrega de invitaciones.
- `app.py`: readiness comprueba `/health/ready` de control y runtime configurados;
  liveness no llama dependencias. Fallos upstream devuelven 503 genérico sin
  datos del proveedor. No verifica directamente DB ni almacenes secretos.
- `settings.py`: URLs HTTP(S) sin credenciales/query/fragmento/puertos inválidos;
  SameSite=None requiere Secure. HTTP local/SameSite=Lax sigue permitido.
- Adaptadores Vault/OpenBao: metadata TTL antes de CAS0 y verificación de
  `deletion_time` de la versión efectiva, incluyendo ganador de CAS. Fail closed
  sin DELETE ambiguo. Nuevo helper técnico `kv_v2_retention.py` y probe opt-in.
  ACL del proveedor debe permitir metadata create/update en namespace temporal.
- Pruebas: matriz pública/aislamiento clasifica history; runner PostgreSQL actual
  incluye `tests/db/test_staff_membership_history.py`. Pruebas BFF ejercitan
  autenticación, autorización/errores, forwarding y ausencia de payload privado.

### Evidencia y límites

- Antes de estos cambios, los nueve checks remotos del SHA
  `388adf5cfda65da06f463a7fcee58ac685895137` aprobaron. Esa evidencia no certifica
  el nuevo working tree ni el despliegue de producción.
- Prueba aislada Vault 1.21.0, puerto 58200: versión inicial con TTL efectivo,
  replay CAS conserva ganador y data GET devuelve 404 después de caducidad.
  Reporta `physical_destruction_proven: false`. Contenedor de prueba eliminado.
  No equivale a prueba real de OpenBao. 120 pruebas focales de stores/assembly
  aprobaron; Ruff y Pyright focales aprobaron.
- Chrome: inventario solo IAB/MCP Apps; `createBrowserTab("chrome",...)` devuelve
  `Browser is not available: chrome`. No recorrido visual/WebAuthn certificado.
- Windows/uv, working tree final: `uv run python scripts/ci/ci_jobs.py python-quality`
  terminó con exit 0; lint, formato, Pyright, scan de secretos, análisis de
  seguridad, auditoría de dependencias, arquitectura, unit y módulos PASS.
  Dos intentos previos detectaron errores del nuevo test BFF: primero formato,
  luego un assertion demasiado amplio que incluía formularios globales. Se
  corrigió el alcance al contenido de la página; la corrida final pasó.
- `uv run pytest tests/unit/admin_console/test_tenant_staff.py -q --tb=short`:
  26 passed, incluyendo seis respuestas de historial y forwarding/redacción.
- PostgreSQL 18 aislado `127.0.0.1:55433/request_engine_admin_verify`:
  `uv run pytest tests/db/test_staff_membership_history.py -q -m postgres --tb=short`:
  4 passed. Comandos reales producen el audit; replay no duplica eventos;
  prueba independiente de empate temporal y UUID, cursor ajeno y revocación.
- Mismo PG: `uv run pytest tests/e2e/test_native_identity_recovery_http.py -q
  -m postgres -k 'test_identity_recovery_delivery or
  test_identity_recovery_ambiguous_delivery_is_not_blindly_retried or
  test_identity_recovery_connection_failure_is_safely_retried' --tb=short`:
  3 passed, 5 deselected.
- Mismo PG: `uv run pytest tests/e2e/test_http_security_matrix.py
  tests/e2e/test_http_tenant_isolation_matrix.py -q -m postgres -k staff --tb=short`:
  17 passed, 102 deselected; incluye historial. `uv run pytest
  tests/e2e/test_public_surface_contract.py -q -m postgres --tb=short`: 4 passed.
  Son pruebas focales, no el runner PostgreSQL completo.
- Docker local puerto 5432: PostgreSQL 18.6 y `alembic_version` =
  `0011_staff_member_profiles`, igual al head vigente. El launcher local
  `run_local_panel.ps1 -ControlPort 8011 -ConsolePort 8012 -RuntimePort 8010`
  terminó correctamente; control/runtime readiness 200; consola readiness
  devuelve ready y OpenAPI runtime publica `staff_history_list`.
  No certifica una sesión de navegador autenticada ni un despliegue productivo.

### Revisión semántica del autor

Contexto: diff de esta continuación, reader y pruebas completos, rutas BFF y
plantillas, contrato Tenancy history, adaptadores KV-v2 y helper, protocolo SRP-1.
El scan de working tree contra origin/development emitió 104 candidatos en todo
el branch; no son 104 defectos de esta continuación ni evidencia exact-head.

- History reader (QR-FSIZE): HEALTHY_AS_IS, confianza alta. Snapshot único mantiene
  autorización/target/cursor juntos; extraer los CTE por LOC ocultaría la frontera.
  Contraargumento: SQL creciente requiere medir volumen antes de aceptar más
  proyecciones. Prueba requerida: RLS/autoridad/cursor/no efectos, ejecutada.
- Tests history y transporte (QR-FSIZE): HEALTHY_AS_IS, confianza alta. Casos
  independientes falsifican defectos distintos; no fragmentar para bajar LOC.
- Rutas staff BFF (QR-FSIZE/QR-CPLX): REVIEW_CONCERN, confianza media. Conviven
  varias páginas relacionadas y ramas de autenticación/errores; nueva history
  no añade mutaciones ni autoridad. Revisar responsabilidad de rutas si crece;
  no crear un proxy genérico ni un camino SQL alternativo. Prueba requerida:
  lint/types/arquitectura y BFF ejecutadas.
- Retention helper: HEALTHY_AS_IS, confianza alta. Abstracción técnica real de
  dos proveedores, no extracción ceremonial; staging/CAS permanecen locales en
  cada adaptador. Contraargumento: versiones/API proveedor distintas requieren
  aceptación real por proveedor, OpenBao real pendiente.

No human_verdict ni aprobación humana inferida. Estos juicios no sustituyen
pruebas deterministas ni autorizan excepciones a garantías.

### Pendientes concretos, sin falsos equivalentes

1. Destrucción física: no existe janitor certificado. Diseñar limpieza por
   namespace cerrado, versiones explícitas y gracia, con reconciliación de
   resultados ambiguos y pruebas de competencia. Soft-delete no es destrucción.
   Retención de snapshots/backups requiere política y aceptación operativa.
2. SMTP real: ejecutar la aceptación existente contra el proveedor/destino
   productivo con secretos protegidos, verificar recepción y reintentos. Mailpit
   y CI no certifican una bandeja externa.
3. Despliegue: aceptar TLS/ingress, cookies, ACL de secretos, backups/restauración,
   alertas y readiness contra el entorno productivo elegido; no se proporcionó
   un destino productivo verificable. Simulaciones P7 no sustituyen esa aceptación.
4. Journey Chrome/passkeys: repetir alta/invitación/preview/accept/tenants/permisos,
   denegaciones y recuperación en Chrome conectado. No guardar secretos reales
   en fixtures ni sustituir Chrome con una prueba ASGI.
5. Perfil/telemetría: definir propiedad y privacidad de contacto confirmado,
   último acceso, sesiones y directorio entre organizaciones. Display name tenant
   y self `my-organizations` no representan esas métricas. No conceder acceso
   global implícito al administrador de plataforma.
6. Publicación: certificado pre-push del SHA final, CI exact-head y revisión antes
   de merge en development; main permanece release-only.

No baseline ni garantías HARD modificadas. No reset ni migración destructiva.

## Continuación adversarial posterior a c696

### Reporte simple (para humanos)

Se cerraron otros fallos encontrados al revisar el branch: solicitudes de un sitio
externo podían iniciar otra cuenta en el navegador, la lista ofrecía una página
inexistente al terminar exactamente llena, y texto de excepciones podía contener
secretos. Se protegen ahora los cambios del panel, la navegación y el diagnóstico.

La herramienta de limpieza nueva es solo para aceptación en servidores de prueba.
No se habilitó en producción: borrar y recrear una clave durante la limpieza
puede hacer que el proveedor destruya una versión nueva. Hay una prueba que
demuestra ese límite; que pase no significa que el algoritmo sea seguro para
producción. Tampoco hay revisión semántica completa de todo el branch.

### Reporte técnico (detallado)

- `app.py::_origin_identity/security_headers`: POST/PUT/PATCH/DELETE exigen un
  único Origin serializado con mismo scheme/host/puerto; normaliza puertos default,
  rechaza ausente/null/malformado/externo antes de upstream o Set-Cookie. APIs
  bearer canónicas no cambian. README del BFF documenta proxy confiable para HTTPS;
  no se leen headers Forwarded de clientes arbitrarios para conceder acceso.
  Clientes de tests declaran su Origin explícito, sin monkeypatch global.
- `test_origin_boundary.py`: 84 casos negativos y flujo same-origin PASS. Prueba
  contra app exacta c696 cargada solo en memoria falló como debe: el Origin atacante
  provocaba 303 y llamada upstream, en vez de 403. No equivale a Chrome real.
- `StaffMembershipPage` en aplicación, reader `limit+1` y DTO HTTP: paginación
  correcta en límite exacto, máximo público 100 inalterado, filtros antes del LIMIT.
  Reader/app Query siguen mismos owner/autoridad/snapshot; no migration/ACL.
- `forms.py::render_path`: percent-encoding por segmento, rechazo de slash,
  backslash y segmentos `.`/`..`; executor captura error antes del forwarding.
  Conserva el suffix de método semántico y no recibe URLs completas.
- `observability.py::JsonFormatter`, `app.py` y `state.py`: error tipo/código y
  request ID en lugar de texto/traceback bruto; incluso debug no muestra texto de
  excepciones. `execution.py` evita incluirlo en payloads de fallos de transporte.
  Se pierde detalle libre deliberadamente; no se promete redacción mágica de todo
  texto arbitrario ni se loguean credenciales para facilitar diagnóstico.
- `temporary_proof_cleanup_acceptance.py` técnico y CLI, primitive
  `probe_expired_temporary_proof_destruction`: recibos tipados, namespace cerrado,
  versiones explícitas, expiry business y provider más grace, reinspection y
  reconciliación. Opt-in, loopback y redirects deshabilitados; operador debe
  garantizar servidor test real, no un túnel a producción. Sin scheduler.
  Contraejemplo de recreación de versión 1 confirma bloqueo HARD; rediseñar
  non-reuse/ACL/discard o conseguir destroy atómico antes de habilitar producción.

Evidencia adicional:

- PG18 aislado: `uv run pytest tests/db/test_staff_membership_lifecycle.py
  tests/db/test_staff_member_profiles.py -q -m postgres --tb=short`: **34 passed**,
  212.39s; cubre límite final, filtros, search, autoridad y lifecycle existentes.
- `uv run pytest tests/modules/tenancy/test_staff_membership_admin_router.py
  -q --tb=short`: **17 passed**, incluyendo totales 50/51/100.
- `uv run pytest tests/unit/admin_console -q --tb=short`: **246 passed** antes
  de añadir cuatro casos adicionales de rechazo de path en el executor.
  Canary de excepción ausente en respuesta, diagnóstico y stderr con debug false/true.
- Stores/cleanup: **123 unit passed**, Ruff/Pyright focal PASS. Probe real aislado
  Vault1.21.0 y OpenBao2.6.1 confirma TTL, ganador CAS, versión destruida y retry
  reconciliado. No certifica físico/backups, ACL producción ni carrera recreación.
  Contenedores test removidos; DB local y datos del usuario preservados.
- Primer bloque c696: certificado local PASS 215.562s; push origin realizado;
  **nueve checks GitHub exact-head SUCCESS**. No se atribuye esa CI al árbol posterior.
- Revisión exacta c696: 108 paquetes v2 validados; 20 relacionados con el primer
  bloque revisados por root, 88 restantes: 16 HEALTHY_AS_IS, 8 REVIEW_CONCERN y
  **64 INSUFFICIENT_CONTEXT**. No aprobación humana inferida ni completitud ficticia.
  Falta lectura semántica completa de SQL/migraciones, WebAuthn/session y pruebas
  asociadas. Las suites verdes no sustituyen esa revisión.

Pendientes siguen siendo los seis enumerados arriba, con la limpieza productiva
explícitamente bloqueada. Verificación agregada final y certificado del nuevo SHA
se registran en los resultados de publicación; la CI del nuevo head es independiente.

### Resultado de validación agregada

`uv run python scripts/ci/ci_jobs.py python-quality --log-dir
.ci/admin-production-final-quality --summary-output .ci/admin-production-final-quality.json`
terminó con exit 0: **201 arquitectura, 908 unit y 645 módulos passed**;
lint/formato/Pyright/secret scan/SAST/dependency audit PASS. Una advertencia
preexistente del cliente de pruebas no constituye un fallo.

Con procesos locales reiniciados sobre este árbol, POST `/login` con Origin externo
devuelve **403 sin Set-Cookie**; `/health/ready` sigue ready. Es prueba HTTP local,
no Chrome. Los resultados PostgreSQL focales arriba siguen siendo los ejecutados;
no se declara una corrida local PostgreSQL completa de este segundo bloque.

El informe de revisión parcial exacta c696, con los 88 IDs y disposiciones,
está preservado en
[`admin-production-branch-review-2026-10-02.md`](admin-production-branch-review-2026-10-02.md).
Sus hallazgos describen ese SHA anterior; paginación, Origin, paths y excepciones
fueron corregidos posteriormente como se detalla aquí. No modificar el informe
histórico para fingir que esos fallos nunca existieron.

## Continuación posterior a 6d68 — validación de formularios

### Reporte simple (para humanos)

Un valor mal escrito ya no se convierte silenciosamente en «desactivar».
Los números imposibles se rechazan antes de enviar la operación, también cuando
aparecen dentro del contenido JSON. Esto evita errores internos y cambios que
el operador no quiso pedir. La API propietaria sigue validando el negocio.

### Reporte técnico (detallado)

`admin_console/forms.py::_coerce` valida el vocabulario booleano explícito y
rechaza números no finitos, incluidos exponentes desbordados y valores anidados.
`parse_submission`/`execute_operation` devuelven el error de formulario 422 antes
de forwarding o creación de una clave de idempotencia. No cambia HTTP/OpenAPI,
capabilities, políticas de negocio ni migraciones.

Prueba focal `uv run pytest tests/unit/admin_console/test_forms.py
tests/unit/admin_console/test_execution.py -q --tb=short`: **37 passed**.
Suite del panel `uv run pytest tests/unit/admin_console -q --tb=short`:
**267 passed**, 18.54s. Ruff focal PASS después de aplicar formato.
Defectos falsificados: booleano desconocido convertido a False; NaN/infinity o
exponente desbordado enviado a serialización HTTP; llamada upstream para entradas
inválidas. Estos resultados pertenecen al árbol de trabajo posterior a 6d68,
no a su certificado ni a su CI remota.

Publicación 6d68: certificado exact-SHA PASS **237.292s** y push origin realizado.
Se finalizaron **112** paquetes quality-evidence/v2 con ese certificado y se
validaron contra JSON Schema Draft 2020-12. Su validez estructural no transforma
los candidatos pendientes en aprobaciones semánticas ni autoriza producción.

## Continuación de autoridad y lectura agrupada — 2026-10-03

### Reporte simple (para humanos)

Una operación ya completada podía devolver su recibo después de retirar el permiso
del administrador. No repetía el cambio, pero omitía revisar su permiso actual.
Se corrigió esa comprobación sin perder la repetición segura de una operación
autorizada. La lista de invitaciones agrupa ahora la lectura de sus estados para
evitar una consulta adicional por cada fila. Ninguno de estos cambios crea una
vía exclusiva del panel ni permite que este escriba directamente en la base.

La primera ejecución real aprobó. La validación general encontró errores de
tipado en la prueba nueva; fueron corregidos y se repite la validación ampliada.
La revisión independiente de sesiones quedó interrumpida por el límite de uso
de los agentes: no se declara terminada ni aprobada por inferencia.

### Reporte técnico (detallado)

- `0012_staff_replay_authority`, único nuevo head posterior a 0011: wrapper
  SECURITY DEFINER `request_cmd.lock_staff_command_authority(text)`, allowlist
  cerrada de tres capabilities, schema owner, PUBLIC revocado, EXECUTE app only.
  Identidad/tenant desde contexto trusted; topology share y ordered tenant staff
  root preceden manager SHARE locks. No tabla, backfill, baseline edit ni DML grant.
- `PostgresStaffMembershipCommands.invite_native_staff/replace_staff_authority/
  transition_staff_membership`: ActorContext ceiling antes de DB y autoridad
  actual bloqueada después de adquirir idempotencia, antes de replay. Contrato
  y evolución documentados en `staff-command-replay-authority.md`.
- `InvitationDeliveryIntent.statuses` y supported Communications contract:
  pares UUID/generation exactos, bounded101, arrays zipped y parámetros bound,
  RLS tenant y columnas públicas mínimas; empty no I/O, missing null. List usa
  esa única lectura, detail/replay singular permanece. READ COMMITTED advisory,
  no promesa de snapshot repetible. Scope no cambia HTTP/OpenAPI/tool/ACL/schema.
- Conteo unitario independiente: **102 → 3 statements para100**, excluyendo
  contexto trusted. No se extrapola a latencia/throughput. Dos pruebas focales
  batch PASS; no sustituyen el proof PostgreSQL.
- Primera corrida: PG18.6 en **55433/request_engine_admin_verify**, aislado del
  contenedor del usuario. `uv run pytest tests/db/test_staff_replay_authority.py
  tests/db/test_staff_invitation_delivery.py -q -m postgres --tb=short`:
  **14 passed**, 102.11s. Recibos creados por comandos reales, grants retirados
  por owner real, replay válido con revision avanzada, no efectos duplicados,
  ActorContext sin capability rechazado y dos ganadores sincronizados mediante
  `pg_blocking_pids`/conexiones independientes. Batch prueba generación exacta,
  duplicados, ausentes, estado anterior y organización extranjera bajo rol app.
- Primer `python-quality` de este bloque falló en Pyright por el test nuevo
  (private fixture import y unions command/callable). Reparado con prerequisites
  públicos y dispatch tipado local al escenario; Pyright focal PASS. No se
  suprimieron checks ni se convirtió ese intento en evidencia verde.

La CI exacta del commit publicado **6d68be43** terminó con **nueve checks pass**.
Esa CI no certifica estos cambios posteriores. Resultados agregados, sincronización
del PostgreSQL local y publicación de este bloque se registran después de ejecutarlos.

### Resultados agregados y revisión del autor

Suite PG18 aislada ampliada: `test_staff_replay_authority.py`,
`test_staff_membership_lifecycle.py`, `test_staff_member_profiles.py` y
`test_staff_invitation_delivery.py`: **48 passed**, 398.59s. La prueba de carrera
recupera un recibo real; nunca lo inserta como resultado esperado. El camino
replay-winner prueba las mismas primitivas de idempotencia/autoridad bajo rol app;
revocation-winner invoca además el comando Python real mientras contiende.

`python-quality --log-dir .ci/admin-replay-batch-final-quality --summary-output
.ci/admin-replay-batch-final-quality.json`: exit0, **201 arquitectura, 925 unit,
647 módulos passed**; Ruff/format/Pyright/secret/SAST/dependency audit PASS.
La única advertencia es del cliente FastAPI existente. Esta corrida precede la
adaptación posterior de `runtime_table_contract.py`, que debe certificar el SHA
publicado; no se atribuye a ese cambio una ejecución anterior.

La verificación adicional del contrato de tablas mostró expectativa obsoleta
para diez tablas privadas nativas de recuperación y de invitación/provisión de
owners. ADAPT de la expectativa, no relajación de INV-PRIVILEGE: el baseline
aceptado ya las mantiene privadas y utiliza request_auth/request_platform
SECURITY DEFINER. Se agregan explícitamente al inventario de tablas sin privilegio
app y se incluye el test en el runner actual. No grants concedidos, no cambios
de baseline y no esperado calculado automáticamente desde la ACL real. Los
intentos iniciales fallidos se conservan como defectos de cobertura descubiertos.

PostgreSQL del usuario: Docker **5432/request_engine_current**, versión18.6,
`alembic upgrade head` aplicado de0011 a0012, sin reset/backfill/deletion. Launcher
local reiniciado; control/runtime ready200 y panel `GET /health/ready` ready.
No prueba autenticada Chrome/Bitwarden ni aceptación SMTP productiva inferida.

Revisión semántica del autor (SRP-1, human_verdict:null): contexto completo de los
comandos de membresía, forms/executor, recorder, unidades list/batch y sus contratos;
SQL0012 y lock roots/manager/idempotency; pruebas completas. Referencias de sensor
estables del checkpoint6d68: QR-5bd9fba198ac (membership commands),
QR-5cde0d167a45 (recorder), QR-63fc30cc8cf1 (executor), QR-8758e2eaf2e9 (forms),
QR-b3cf1ae40f2c (delivery tests). HEALTHY_AS_IS, confianza alta para estas unidades:
orquestación tipada por owner, locks ordenados y fases explícitas; sin extracción
por LOC. Contraargumentos: raíz tenant amplia serializa administraciones y decoder
JSON no sustituye límites transport/business; ninguna medición throughput validada.
No cambiar raíces para reducir complejidad sin prueba de concurrencia.
QR-d994de76754d (invitation commands): HEALTHY_AS_IS para la unidad list/batch,
confianza media; el resto de SQL/carreras conserva la revisión parcial previa.
No se convierte el estado de todo el archivo ni los demás 64 candidatos en aprobado.
Estos IDs identifican sujetos del paquete anterior, no certifican hechos de un SHA
nuevo. El certificado final y CI exact-head siguen siendo independientes.

Después de ADAPT explícito, `uv run pytest
tests/db/test_app_function_privilege_inventory.py
tests/db/test_v3_runtime_privilege_contract.py -q -m postgres --tb=short`:
**4 passed**, 23.82s, mismo PG18 aislado y login app real. No permisos productivos
ampliados. `git diff --check` y Ruff focal PASS; hook gestionado pre-push instalado.
