# PR 137 — revisión de preparación productiva de la API

Fecha: 2026-10-06. Alcance: API, autenticación, autoridad, persistencia, contratos,
evidencia y operación. La UI administrativa está excluida.

Este informe conserva los hallazgos y resultados del candidato auditado el
6 de octubre. Para el estado posterior de las correcciones, consultar la
[actualización del candidato del 8 de octubre](#actualizacion-del-candidato-2026-10-08).

## Reporte simple (para humanos)

**Veredicto: no certificar ni lanzar la API a producción en este estado.**

No es un veredicto basado solamente en trabajo pendiente de infraestructura.
Encontramos un fallo real: un administrador legítimamente autorizado pudo añadir
17 permisos al controlador de una organización mientras ese controlador estaba
en recuperación de cuenta. El controlador había dado consentimiento antes de
iniciar la recuperación. Su sesión anterior ya había sido rechazada, pero el
cambio de permisos todavía se aceptó y quedó guardado. La protección de
recuperación y la concesión de permisos no están conectadas correctamente.

También demostramos que el login sin nombre acepta una respuesta con el
identificador de usuario de la passkey ausente o incorrecto. La especificación
WebAuthn exige comprobar esa asociación. La firma sigue verificándose y la cuenta
se selecciona por la credencial guardada: **no demostramos toma de una cuenta
ajena**, pero no es correcto certificar el recorrido como una implementación
completa del protocolo.

Hay otros dos comportamientos que requieren cerrar su contrato antes de lanzar:

- Una credencial de otra autoridad nativa activa inició sesión en una API
  configurada para una autoridad diferente. Ocurre si existen ambas autoridades
  en la misma base. Hay que decidir cuáles son las autoridades aceptadas; no
  asumir que el parámetro de configuración ya limita este recorrido.
- Un desafío de login venció mientras esperaba un bloqueo de base de datos y,
  después, creó una sesión. Un desafío ya vencido fue rechazado cuando la
  operación empezó después del vencimiento. Hay que fijar si el vencimiento
  limita la admisión inicial o la creación definitiva de sesión, y probarlo.

Esto convive con avances importantes y verificados. Todos los checks actuales
del PR están verdes. Revisamos los resultados y logs, no solamente la insignia:
la batería de producto contiene 1.444 ejecuciones sin fallos. La instalación
limpia funcionó. Repetimos 51 pruebas focales y toda la batería local de calidad,
con resultado correcto. Sin embargo, las seis comprobaciones adversariales
nuevas dieron **cinco fallos y un caso correcto**. Un verde solo responde las
preguntas que las pruebas existentes saben hacer.

La API ya tiene recorridos reales de instalación, passkeys, recuperación,
organizaciones, personal, invitaciones, configuración, reservas y agentes. No
recomendamos reconstruir esas funciones ni añadir pantallas para ocultar los
fallos. Primero deben conectarse correctamente los controles y convertirse los
hallazgos en pruebas permanentes.

Además falta aceptar el entorno donde se desplegará. La base local que suele
usar el launcher está ocho migraciones atrás del código; no fue actualizada aquí.
No confirmé qué base usa un proceso de aplicación ya abierto.
Correo de prueba y restauraciones de laboratorio funcionan, pero todavía no
acreditan correo externo, ingreso HTTPS privado, permisos efectivos del gestor
de secretos, recuperación de los backups reales, alertas o comportamiento bajo
carga. La limpieza de secretos temporales existe, pero requiere admisión y una
ejecución programada expresamente verificadas.

Hay inconsistencias menores de contrato: un indicador de revisión de permisos
describe una cosa distinta de la que calcula; la repetición de un consentimiento
caducado puede describirlo como pendiente. También faltan pruebas específicas de
algunas retiradas de autoridad. El procesamiento final de solicitudes debe
aceptarse si forma parte de la promesa del producto: las operaciones internas
existen, pero no se certificó un consumidor desplegado que termine ese recorrido.

Esta revisión fue orientada a riesgos. Inventariamos las superficies de ambas
API y contrastamos contratos, código y evidencia. **No es una revisión manual
exhaustiva de cada operación ni una aceptación del despliegue real.** Cuatro
revisiones independientes con GPT-6 Luna ayudaron a investigar y contrastar los
hallazgos; las conclusiones importantes se verificaron personalmente.

Entregamos este informe y pruebas diagnósticas locales. No corregimos la
implementación, no cambiamos la UI, no migramos datos de la aplicación, ni hicimos
commit, push, merge o despliegue. Los fallos reproducidos siguen pendientes.

## Reporte técnico (detallado)

### 1. Candidato, método y alcance de la afirmación

| Identidad | Valor verificado |
| --- | --- |
| PR | [#137](https://github.com/JulioMarte/request-engine/pull/137), OPEN |
| Título | `feat: discoverable usernameless passkey login + private admin console` |
| Rama | `feature/admin-console` |
| Source HEAD | `7f2ccb10fd116fca952c61759a5dc52f28e57b2a` |
| Base `origin/development` | `1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d` |
| Merge candidate evaluado en GitHub | `415841d1cc9f914c3806cba08cb0be2f56fe45ae` |
| Parents del merge candidate | Base anterior + Source HEAD anterior |
| Estado consultado al cierre de pruebas | Nueve checks SUCCESS; mergeStateStatus CLEAN |
| Head de migraciones | `0033_adopt_fact_tenant_rls` |
| Diff respecto a development | 492 archivos; 51.303 inserciones y 901 eliminaciones |

El título ya no expresa el tamaño del cambio: incluye migraciones 0002–0033,
autoridad de staff, adopción de políticas, configuración administrativa,
Requests, presupuestos y retención. Un review limitado al primer commit no
certificaría el branch actual.

Autoridad consultada: política de optimización, mapa de documentación,
garantías actuales, contratos de autoridad administrativa, ADR 0014/0016,
contratos de autenticación/recuperación/retención, documentación de testing y
reglas de evidencia. Los checkpoints históricos no sustituyen el código actual.

Convención de rutas abreviadas en los hallazgos: `tenancy/`, `booking/` y otros
owners se resuelven bajo `src/request_engine/modules/`; `platform/` bajo
`src/request_engine/`; nombres de migración bajo `migrations/versions/`.

La copia local tenía cambios preexistentes en el launcher y archivos de la UI,
además de documentos/scripts sin seguimiento. Se conservaron. El backend
auditado coincide con HEAD; la batería local completa incluyó también la copia
local de las pruebas de UI, por lo que no se presenta como un checkout limpio.
La evidencia remota sí está vinculada al candidato de integración indicado.

**Límites:** inspección manual orientada a superficies críticas y tres revisiones
especializadas inicialmente acotadas a aproximadamente 15 archivos cada una,
más una revisión independiente de los probes. No se inspeccionaron manualmente
todas las implementaciones de las 306 definiciones de operación. Para el resto,
se revisó inventario/evidencia, no se infiere ausencia de defectos. Tampoco se
midió cobertura de código, carga ni infraestructura productiva.

### 2. Inventario de API y funcionalidad presente

Se compusieron las factories y sus OpenAPI sin abrir conexión DB. Resultado:

| Superficie | Operaciones OpenAPI | Propietarios y recuentos |
| --- | ---: | --- |
| Native/data-plane | 221 | tenancy 71; requests 9; catalog 15; booking 22; queue 22; delivery 8; live_capacity 7; communications 5; onboarding 1; operational_recovery 9; operational_copilot 20; discovery 6; técnicas/sin owner anotado 26 |
| Platform control | 85 | tenancy 33; platform_configuration 20; técnicas/sin owner anotado 32 |

No se encontraron `operationId` duplicados **dentro de cada app**, ni operaciones
con capability anotada y owner ausente. Hay operaciones compartidas entre apps:
221 + 85 no significa 306 operaciones de negocio distintas. El inventario no
comprueba autorización, startup, providers o todos los errores reales.

| Área | Implementación/evidencia presente | Lo que aún impide afirmar certificación |
| --- | --- | --- |
| Instalación y trust root | Claim HTTP, passkey real, cierre permanente del setup, recuperación offline; Docker foundation PASS | Aceptación de ingreso privado, custodia humana y restore productivo |
| Login y sesiones | Password y WebAuthn, evidencia derivada, step-up, revocación, opciones anti-enumeración | R-02/R-03/R-04; nuevas negativas discoverable |
| Tenancy/staff | Organizaciones propias, directorio de plataforma, perfiles, historial, invitaciones, ceilings y replay | R-01; matrices faltantes; contratos R-05/R-06 |
| Políticas antiguas | Adopción dual-consent implementada en 0026–0033; apply/apply, withdraw y owner-revoke probados | Recuperación del controller no queda protegida; adopción externa completamente fixture-free no se acreditó aquí |
| Catalog/Booking/supply | Lecturas de reconstrucción, configuración/revisiones, decimal exacto, capacidad y consistencia | Matriz por comando de retirada/replay y aceptación bajo carga |
| Communications | Intent durable, worker, entrega gobernada, SMTP y rotación/hot reload | Correo real y alertas/backlog en despliegue |
| Requests | Definiciones versionadas, inbox, schema exacto, RE2, lifecycle interno | Consumidor operativo si se promete procesamiento hasta estado terminal |
| Agentes | Activación acotada, grants/policy explícitos, catálogo, rotación, denegación y suspensión | Evidencia final debe conservar identidad/autoridad; no implica MCP distribuido |
| Secretos/retención | Inventario, cleanup con lease/fence/reconciliación y CLI separado | Admisión real, schedule, renovación del artifact y restore fence |
| Operación | Budgets HTTP/password/SQL, telemetría y simulación de recuperación | Dimensionamiento, SLO/alertas y recuperación del entorno real |

No se exige CRUD de cada tabla, exposición de comandos internos, SDK/MCP ni UI
como sustitutos de estos controles.

### 3. Evidencia ejecutada y logs revisados

#### 3.1 GitHub: estado actual frente al histórico

- [CI 37512613867](https://github.com/JulioMarte/request-engine/actions/runs/37512613867):
  Python quality, PostgreSQL current-product, observabilidad y V2 history PASS.
  El check «V3 candidate and verticals» es un **aggregate de prerrequisitos**, no
  una segunda batería independiente; no duplicar su evidencia.
- [Docker 37512613891](https://github.com/JulioMarte/request-engine/actions/runs/37512613891):
  smoke, f01-foundation, worker-restart, recovery-delivery,
  platform-configuration y clone-fence PASS. No equivale a ejecutar `all`.
- [P7 37512613868](https://github.com/JulioMarte/request-engine/actions/runs/37512613868):
  governed configuration check SUCCESS; estado consultado, no análisis detallado
  adicional de todos sus logs en esta revisión.
- [Recovery simulation 37512613954](https://github.com/JulioMarte/request-engine/actions/runs/37512613954):
  logs y artifacts revisados. PostgreSQL clean-target restore y OpenBao Raft
  restore `outcome=accepted`; clone fence impidió efectos SMTP/outbox.
- [Coolify contract 37512613955](https://github.com/JulioMarte/request-engine/actions/runs/37512613955):
  check SUCCESS. No se inspeccionó ni aceptó una instalación real de Coolify.

Los 24 JUnit descargados de `current-product-proof` suman **1.444 casos, 0 failures,
0 errors y 0 skipped**. Entre ellos: e2e 469, principal-authority 465,
semantic-commands 113, schema 37 y operational-safety 74. Son ejecuciones; no
contabilizar como pruebas únicas sin deduplicarlas. `proof-execution.json` tiene
`gaps: []`: eso acredita el mapa de archivos existente, no cada escenario adversarial.

Checkpoints explícitamente inspeccionados: login del owner por TCP, agente
positivo/rotación/denegación, invitación revocada sin membership, paginación real,
aceptación con cero grants iniciales, recovery delivery de uso único, worker
hot reload, reinicio del worker y bloqueo de outbound en clone.

El run anterior [37507400648](https://github.com/JulioMarte/request-engine/actions/runs/37507400648),
HEAD `72b2d38…`, falló con **1 failed / 464 passed / 2 deselected**. Su log señala
`test_public_http_surface_cannot_grow_without_e2e_classification`: faltaban las
tres rutas tenant de adopción en el inventario. Ese fallo está superado por el
run actual. No tratarlo como bug pendiente ni interpretar sus rechazos DB de
pruebas negativas como incidentes de producción.

#### 3.2 Entorno y nuevas comprobaciones locales

Windows; `uv run python --version`: Python 3.13.1; uv 0.10.4. El `python` global
es 3.14.7 y **no** fue el intérprete usado por pytest/quality. GitHub declara
Python 3.13.15/uv 0.12.5. No se oculta esta diferencia de toolchain.

Base desechable independiente: contenedor `request-engine-pr137-audit-20261006`,
imagen `postgres:18.6`, host `127.0.0.1:65237`, DB `pr137_audit`.
`uv run alembic upgrade head` instaló 0001–0033 y la consulta posterior confirmó
`0033_adopt_fact_tenant_rls`. Las acciones bajo prueba usan LOGINs heredando solo
los roles app/control pertinentes; admin se usa para precondiciones y oráculos.

| Ejecución | Resultado |
| --- | --- |
| `uv run python scripts/ci/ci_jobs.py python-quality --log-dir .ci/pr137-production-audit-20261006/local-quality-complete --summary-output .ci/pr137-production-audit-20261006/local-quality-complete/summary.json` | 12/12 PASS, exit 0 |
| Arquitectura/unit/modules de esa ejecución | 203 / 1.079 / 752 PASS; una advertencia de deprecación en unit |
| Focal PostgreSQL/WebAuthn/adopción/budget | 51 PASS en 229,07 s |
| Probes iniciales, cuatro casos | 3 FAIL / 1 PASS en 18,32 s |
| Probes finales, seis casos | **5 FAIL / 1 PASS en 21,93 s**, exit 1 |
| `inventory_api.py` | 221/85 operaciones; sin IDs duplicados ni capability sin owner |
| Oráculo de limpieza posterior | 0 native_sessions y 0 adoption_facts en la DB desechable |
| `uv run pytest tests/architecture/test_documentation_change_contract.py -q`, tras crear el informe/índice | 6 PASS en 1,77 s |
| `git diff --check` | Exit 0; solo avisos de LF/CRLF en cambios preexistentes de UI/launcher |

La primera ejecución local de quality fue abortada después de cinco pasos PASS;
es incompleta. La ejecución `local-quality-complete` es independiente y sí
terminó. La primera invocación de los probes falló en collection al usar
`uv run pytest` fuera del árbol `tests`; se corrigió la invocación a
`uv run python -m pytest`. Ese error de harness no cuenta como defecto del API.

Focal ejecutado, con `PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD` dirigidos solo a
la DB desechable y sin DSNs runtime heredados:

```text
uv run pytest
  tests/db/test_webauthn_persistence.py
  tests/db/test_webauthn_concurrency.py
  tests/e2e/test_native_webauthn_login_http.py
  tests/e2e/test_controller_policy_adoption_http.py
  tests/e2e/test_controller_policy_adoption_native_http.py
  tests/e2e/test_controller_policy_adoption_concurrency.py
  tests/e2e/test_controller_policy_adoption_apply_race.py
  tests/e2e/test_controller_policy_adoption_owner_revocation_race.py
  tests/db/test_controller_policy_adoption_provenance.py
  tests/db/test_http_sql_execution_budget.py
  -q --tb=short
  --junitxml=.ci/pr137-production-audit-20261006/local-focal.xml
```

Probes finales:

```text
uv run python -m pytest
  .ci/pr137-production-audit-20261006/test_adversarial_probes.py
  -q -s --tb=short
  --junitxml=.ci/pr137-production-audit-20261006/adversarial-final.xml
```

El script rechaza collection fuera de `PGPORT=65237`/`PGDATABASE=pr137_audit`.
Usa fixtures canónicas explícitas, estado inicial plausible, firmas reales y
oráculos de filas. No deshabilita triggers/RLS ni fabrica sessions/adoption facts
de salida. Las autoridades iniciales proceden en parte de builders privilegiados:
**no es una prueba de onboarding fixture-free ni una certificación TCP/ingress**.
Consentimiento, recuperación y apply sí atraviesan las factories HTTP reales.

Artefactos locales: `.ci/pr137-production-audit-20261006/`, incluyendo los scripts
`test_adversarial_probes.py`, `summarize_evidence.py`, `inventory_api.py`,
`api-inventory.json`, XML y artifacts GitHub descargados. `.ci` está ignorado:
estos probes todavía **no son regresiones permanentes ni forman parte de CI**.
Preservar el paquete local y trasladar los escenarios a sus suites canónicas al
implementar correcciones; no depender de este directorio en un clon nuevo.

### 4. Hallazgos prioritarios y tareas ejecutables

P0 significa blocker de seguridad/lanzamiento. P1 requiere cierre antes de la
promesa productiva afectada. P2 es coherencia/mejora de menor severidad. Se
separan hechos reproducidos, inspección estática y aceptación operativa pendiente.

#### R-01 — P0: recuperación del controller no invalida la admisión de adopción

**Estado: defecto reproducido; corrección pendiente.**

Owner: Tenancy, en conexión explícita con autenticación nativa. Operación:
`platform_controller_policy_adoption_apply`; capability
`platform.organization.adopt_initial_controller_policy`. Garantías:
`INV-CONTROLLER-POLICY-ADOPTION-001`, recuperación restringida y autoridad explícita.

Fuentes:

- `src/request_engine/modules/tenancy/adapters/db/controller_policy_adoption_commands.py::apply_adoption`,
  líneas 175–221: verifica la evidencia ingress del actor platform.
- `migrations/versions/0032_adopt_column_acls.py::apply_controller_policy_adoption`,
  líneas 139–168: valida bindings, Principal activo y authority_revision del root;
  no consulta `native_identity_recovery_state` del controller.
- ADR 0016, límites 3 y consistency gate: sujetos recovery-restricted no participan;
  ambas rutas nativas actuales deben validarse.

**Reproducción ejecutada:**

1. Identidades root/owner distintas y root legacy válido.
2. Login HTTP con WebAuthn real para ambos; emisión HTTP de códigos para root.
3. Root crea consentimiento por API.
4. `POST /auth/native/password:recover-with-code` inicia recuperación del root.
5. DB: `recovery_restricted`; authority_revision del Principal no cambia.
6. El token anterior del root responde 401: la recuperación sí invalida sesiones.
7. Owner autorizado llama `:apply` con la revisión del consentimiento.
8. **HTTP 200, un adoption fact y 17 grants nuevos**.

No es escalamiento anónimo ni una firma falsificada. Es aplicación de autoridad
por un approver legítimo después de que el controller dejó de ser admisible.
El guard del approver no valida la postura del target.

**Implementación requerida:**

1. Diseñar la admisión transaccional del controller y approver: autoridad nativa
   activa, identidad activa, binding correcto y postura no restringida.
2. Vincular el consentimiento a evidencia/época nativa suficiente para decidir
   si una recuperación posterior exige consentimiento nuevo. La revisión de
   grants por sí sola no representa la recuperación. Fijar también la política
   después de recovery completion; no restaurar silenciosamente consentimiento.
3. Revisar el orden completo de locks frente a recovery, disable, session revoke,
   owner revoke y staff suspension **antes** de añadir locks nativos al SQL actual.
   No insertar un lock de identidad detrás de locks incompatibles de Principal.
4. Reutilizar/diseñar un primitivo estrecho de auth. Hay precedente en
   `0019_native_provision_reachability::lock_accepted_native_credential` y
   `0022_native_provision_session::lock_accepted_native_session`; no copiar sus
   firmas sin comprobar que la evidencia del consentimiento y actor es la correcta.
5. Append migration desde el head efectivo. Mantener ACL de columnas, RLS,
   opacidad y roll-forward; no editar 0032 ni el baseline.
6. Rechazar con error owner tipado 403/409 y cero grants/facts/receipt/efectos de
   salida. Revisar replay por separado: resultado histórico no crea autoridad,
   pero su lectura debe tener admisión actual explícita.

**Salida:** convertir el probe en regresión HTTP/PG durable; casos recovery antes
de consent, después de consent y concurrente con apply, en ambos órdenes;
controller y approver; logout/disable/recovery-complete por separado.
Sin sleeps como única coordinación. Inspeccionar epoch/posture, grants, facts,
audit, receipts y ausencia de efectos del perdedor. Ejecutar current-product y CI
exact-candidate. No basta probar un ActorContext construido con `recovery_restricted=True`.

#### R-02 — P1: `userHandle` no se valida en login discoverable

**Estado: dos negativas reproducidas; corrección de protocolo pendiente.**

Fuentes: `src/request_engine/platform/security/native_webauthn_auth.py::complete_discoverable_authentication`
368–400; `src/request_engine/platform/security/webauthn.py::verify_authentication` 374–403;
`src/request_engine/platform/db/webauthn_store.py::read_credential` 98–119.

[WebAuthn Level 3 §7.2, paso 6](https://www.w3.org/TR/webauthn-3/#sctn-verifying-assertion)
exige `userHandle` presente cuando la cuenta no se identificó antes de la ceremonia,
y verificar su asociación con la cuenta que contiene `rawId`. Para cuenta ya
identificada, comprobar el handle cuando está presente.

El probe registró la key con el handle emitido por el servidor. Luego presentó
una assertion genuina, primero con `userHandle=null` y luego con otro handle.
Ambas crearon una sesión durable. No se eligió la cuenta equivocada: la identidad
sigue viniendo de credential ID. El defecto es la comprobación faltante del RP,
no prueba de robo de cuenta sin clave privada.

**Implementación requerida:**

1. Persistir o recuperar confiablemente el handle realmente emitido para cada
   credencial/cuenta. No inventar su valor a partir del input del login.
2. Atención al claim: `_setup_user_handle(setup_session_id)` difiere de
   `_user_handle(native_identity_id)`. La promoción de la passkey de setup debe
   conservar esa asociación. Comparar siempre con SHA(native_identity) bloquearía
   credenciales legítimas del primer owner.
3. Diseñar backfill/compatibilidad para credenciales existentes con procedencia
   setup versus registro normal; no borrar claves ni reescribir baseline.
4. Comparar presencia/asociación antes de finalizar; preservar identidad autoritativa
   derivada de credential ID y ausencia de disclosures ante errores.
5. Corregir `tests/fixtures/software_webauthn_authenticator.py`: hoy genera un
   handle aleatorio. Los builders deben incorporar el `user.id` de registration
   options para producir un caso válido. Cambiar ese fixture sin el guard no
   constituye evidencia de la corrección.

**Salida:** correct handle funciona; null/ausente/ajeno falla sin session ni
consumo; mismo control con login de handle y passkey promovida del claim;
firma/origin/RP/UV/replay siguen fail-closed. Añadir negativos HTTP y PostgreSQL,
no solo un mock del verificador.

Una observación de la revisión independiente cuestionó la exigencia de presencia.
Se descartó esa observación después de consultar el texto oficial: la rama
**user was not identified** del paso 6 la exige expresamente. No aceptar sin
contraste ni las conclusiones de este revisor ni las del modelo especializado.

#### R-03 — P1: caducidad admitida antes de locks, sesión escrita después del vencimiento

**Estado: comportamiento reproducido; contrato temporal y tratamiento pendientes.**

Fuente: `0002_discoverable_webauthn_login::finalize_discoverable_webauthn_authentication`,
líneas 213–222 versus 243–298. El challenge se valida/bloquea antes de esperar
la identidad; solo se vuelve a comprobar el expiry de la **sesión nueva**, no
el expiry del challenge, al continuar.

Con TTL de dos segundos y dos conexiones reales se observó el finalizer esperando
al PID que bloqueaba la identidad. Se esperó el vencimiento según el reloj DB,
se liberó el lock y apareció `('consumed', consumed_at > expires_at=True, sessions=1)`.
Control independiente: iniciar la operación después de expiración produce
`webauthn_challenge_unknown` y cero sessions. No se mockeó reloj ni verificación.
El TTL reducido acelera el mismo interleaving cercano al vencimiento; no prueba
una configuración productiva particular.

**Decisión obligatoria:** fijar explícitamente si TTL termina en la admisión del
challenge o en la consecuencia definitiva. Bajo rechazo estricto en finalización,
esto es un defecto de concurrencia. Bajo admisión pre-expiry, hay que documentar
el punto de linearización y acotar la demora; el test de rechazo al final no sería
el oráculo apropiado. No afirmar que se aceptó una assertion que llegó inicialmente
con un challenge ya vencido ni que esto permite login sin firma.

**Recomendación:** política estricta; revalidar contra `clock_timestamp()` después
de los locks necesarios y antes de efectos, con salida tipada y rollback/no sesión.
Revisar además registration/step-up y finalizers heredados que comparten patrón;
solo discoverable se reprodujo aquí. Nueva migración, no edición del baseline.

**Salida:** ambos casos y replay quedan cubiertos; probar bloqueo de identidad,
credencial y autoridad, y que el rechazo no muta sign_count/last_used/session.
Una decisión alternativa necesita contrato explícito y pruebas del límite real,
no simplemente retirar el probe para mantener CI verde.

#### R-04 — P1 condicional: login sin nombre no hereda el límite de autoridad configurada

**Estado: mismatch reproducido; alcance de confianza por decidir.**

Fuente: `src/request_engine/platform/security/native_webauthn_login.py::complete_login` 71–79; auth service discoverable;
0002 finalizer 225–240. Login con handle resuelve usando `identity_authority_id`;
sin handle acepta la identidad de cualquier credencial cuya autoridad sea native
y active, sin comparar con la autoridad configurada.

Una app compuesta con A emitió HTTP 201 y una sesión para una credencial de B.
Las dos autoridades iniciales fueron precondiciones legales de PostgreSQL; no
se acreditó que el provisioning público productivo pueda crear B. Principal,
binding, tenant y capability checks posteriores siguen siendo obligatorios.
No se demostró acceso a datos de otro tenant.

**Implementación/decisión requerida:** definir una autoridad o un conjunto explícito
de autoridades aceptadas para esa superficie. Si A es el límite, trasladar esa
identidad trusted al finalizer y validarla bajo locks; no aceptar un authority UUID
del body. Si varias son intencionales, documentar la política única para password,
passkey, step-up y session consumption. No usar `active` por accidente como segundo
registro de confianza.

**Salida:** dos autoridades y credenciales genuinas; permitido A, B no permitida,
B desactivada, handle correcto/incorrecto y omisión; cero session ante rechazo.
Si la instalación garantiza una única native authority, demostrar esa restricción
por DB/startup y migración, no solo con el fixture habitual.

#### R-05 — P2: indicador de revisión de permisos semánticamente incorrecto

**Estado: confirmado por lectura; no bypass observado.**

`tenancy/api/controller_policy_adoption_routes.py::ControllerPolicyAdoptionReviewView`
142–148 y `_review_view` describen `capability_delta_is_non_revoking` como ausencia
de eliminación de grants actuales. En realidad se calcula como
`not revoked_capabilities`; SQL 0032, 306–316, produce capacidades del target con
historia revocada y sin grant activo. Es riesgo de **restauración de autoridad
revocada**, no eliminación. Apply ya rechaza esa restauración.

Corregir conjuntamente nombre/descripción/OpenAPI/ADR 0016 170–175 y consumidores
API. Mantener la aclaración «no es elegibilidad de apply». Puede bastar corregir
descripción en preproducción; si se renombra, disposition del contrato y pruebas.
Salida: casos sin revocaciones, con revocación y con consentimiento no aplicable;
el indicador describe exactamente su conjunto y nunca sustituye autorización.

#### R-06 — P2: replay de consentimiento vencido puede anunciar `pending`

**Estado: lectura estática; no reproducción temporal de 24 horas en esta auditoría.**

`0027_controller_policy_adoption::request_controller_policy_adoption` 216–225
retorna el status persistido antes de materializar expiraciones 234–237.
`read_controller_policy_adoption` proyecta `expired` con reloj DB. Un mismo
recurso puede resultar pending en POST replay y expired en GET. Apply comprueba
expiry y no se observó reactivación.

Definir respuesta de replay histórico frente a estado vigente; preferir estado
efectivo coherente sin crear otro consentimiento ni renovar TTL. Añadir prueba
temporal mediante mecanismo confiable de test, sin fabricar el resultado del
command. Salida: replay/GET acordados o diferencia explícitamente contractual;
apply vencido denegado y ninguna concesión nueva.

#### R-07 — P1 de evidencia: matriz de autoridad/replay no está cerrada por owner

El contrato `administrative-transaction-authority.md` reconoce alcance limitado.
Booking/Catalog legacy revalidan Representation antes del receipt; Requests y
algunas nuevas lecturas/configuraciones también validan standing capability.
No son controles equivalentes sobre sesión, delegación, agent policy o features.
Ejemplo concreto: `booking/adapters/db/contextual_config_commands.py` 63–82
usa `require_operational_authority` antes del receipt. No inferir un check global
de todas las capabilities a partir de eso.

Crear una matriz por operación modificada: owner, capability publicada, scope,
lock root, punto de admisión, política de replay, withdrawn grant/Representation,
Party inactiva y ambos órdenes de concurrencia. Priorizar resource create,
assignment create/supersede/retire, availability, terms y exceptions; después
Catalog bootstrap/profile/hours y Communications. Conservar sus contratos, no
añadir un wrapper global ni usar receipt namespace como capability pública.

Hay regresiones reales existentes y verdes. La laguna es el alcance restante,
no evidencia de que todos esos comandos sean vulnerables. El posible bypass
«membership suspended pero binding y principal activos» del revisor tampoco se
acepta como bug confirmado: `transition_staff_membership` modifica ambos y
revoca sesiones. Lo pendiente son interleavings soportados y sus oráculos.

### 5. Gates operativos y producto: qué falta implementar o aceptar

| Gate | Trabajo concreto | Criterio de salida y evidencia |
| --- | --- | --- |
| O-01, P0 lanzamiento | Declarar entorno, artifact/digest, exposición data/control, HTTPS, RP/origins y proxies confiados; verificar roles efectivos | Pruebas desde redes pública y privada; control-plane inaccesible desde la pública, setup cerrado tras claim, TLS/hostname y origen incorrecto rechazados, LOGINs sin superuser/BYPASSRLS/memberships extra |
| O-02, P1 migración | Ensayo desde copia poblada de la revisión realmente instalada; backup, locks/timeout y roll-forward | 0025→head conserva identidades, passkeys, grants y facts; replay no backfill implícito; instalación limpia y multibase PASS son pruebas distintas del upgrade poblado |
| O-03, P1 capacidad/abuso | Dimensionar pools por proceso/réplica, HTTP y hashing; límites de ingreso y rate de emisión de challenges | Carga acordada con CPU/RSS/connections/latencias; rechazo acotado y rollback; sin starvation de probes. Defaults por proceso no son presupuesto global |
| O-04, P1 entrega | Configuración SMTP gobernada, secreto real, dominio/remitente/TLS, operación del worker | Invitación y recovery en destino real de prueba; fallo definitivo, ambiguo, resend/revoke/expiry/reconciliación; alertas por backlog. Mailpit no demuestra entrega externa |
| O-05, P0 si se promete destrucción | Desplegar CLI cleanup separada y schedule; admisión efectiva de todos los writers, permisos negativos, backend UUID y fence de restore | Evidencia de policy real sin metadata DELETE/recreation/plaintext; renewal antes de 24 h, progreso y lease loser; crash/ambigüedad no blind retry; restore revoca credenciales y recertifica |
| O-06, P0 recuperación | Backup PG + topology/credenciales y OpenBao en almacenamiento real; restaurar sin fuente disponible; clone outbound fence | RPO/RTO definidos y medidos; recuperación de secrets/credenciales por canal aparte; operador ejecuta runbook; cero correo/outbox del clone hasta liberación autorizada |
| O-07, P1 operación | Alertas efectivas y progreso del worker, no solamente proceso vivo | Inducir worker detenido/atascado, SMTP/Vault down, pool saturado, lease stale y error de auth; alerta llega al responsable dentro del umbral; correlación sin secrets |
| O-08, P1 condicionado | Definir consumidor de Requests y su autoridad si se promete submit→resultado terminal | Journey externo mediante contracts owners, definición exacta, retry/cancel/race, result validation y observación terminal; no SQL directo ni publicar internos indiscriminadamente |
| O-09, P1 certificación | Estabilizar candidato, review semántico actual, repetir lanes pertinentes y GitHub integration-candidate | Nuevos probes incluidos durablemente; CI no omite escenarios; vínculo source/base/tested SHA/digest y acta de aceptación del entorno |

Precisiones para ejecutar estos gates:

- `platform/http/request_budget.py` ya limita body/concurrencia/timeouts por
  proceso: defaults 1 MiB/128 requests/4 auth. No es rate limit global. 0002
  permite emitir challenges discoverable nuevos sin expirar otros ni cap de
  pendientes; revisar crecimiento/retención y abuso de emisión. Es inspección
  estática, no prueba ejecutada de saturación o agotamiento de disco.
- `PostgresExecutionBudget` ya fija statement/lock/transaction/idle/pool timeouts.
  `create_postgres_engine` no configura explícitamente `pool_size/max_overflow`.
  Aceptar su total entre API/control/worker/réplicas o exponer configuración
  acotada; no asumir que las 128 admisiones equivalen a 128 conexiones.
- `bootstrap/server.py::ready` verifica autoridad nativa/DB y firma gestionada.
  No sustituye la señal de progreso de workers ni la aceptación de providers.
  Conservar readiness semánticamente acotada y añadir señales independientes;
  no convertirla en autoridad ni hacer caer toda API por una capacidad opcional.
- Cleanup **ya existe** en `temporary_proof_cleanup_worker.py` y su CLI. No está
  montada automáticamente en `build_worker_process`; es una admisión separada
  deliberada. Certificar schedule y seguridad; no activarla eliminando el fence.
- La simulación ya ejecutó restore limpio PG/OpenBao. Lo pendiente es backup
  real, credentials, custodia/HA y tiempos aceptados. Destruction KV no acredita
  borrado de medios/backups; tampoco inventar una garantía regulatoria.
- Requests tiene result/complete/fail internos y outbox. El public composition
  excluye internals deliberadamente. No declarar que el lifecycle no existe:
  decidir y aceptar el consumidor que lo opera.

### 6. Coherencia documental y revisión de mantenibilidad

`auth-implementation-status.md` todavía presenta como pendientes decisiones o
capacidades implementadas después de sus checkpoints; su bloque actual dice
ADR 0016 propuesto aunque está Accepted e implementado. El closure plan contiene
checkpoints previos a 0026–0033. `administrative-transaction-authority.md` enumera
adopciones nuevas, pero conserva límites redactados antes de ellas.

Actualizar bloques de **estado vigente** al cerrar los fixes; conservar fechas y
provenance histórica. Un informe local de HEAD 72b2d38 no describe el estado
actual de CI 7f2ccb10. Este informe es diagnóstico, no sustituye contratos owners.

El artifact quality actual contiene 258 `REVIEW_CANDIDATE` packets con source/tested
SHA correctos. Eso no son 258 defects ni una aceptación semántica. La calibración
adjunta tiene cuatro observaciones de modelo y cero human labels; no acredita
review final de todo el branch. Priorizar owners y conexiones cambiadas y aplicar
el protocolo semántico vigente, admitiendo `HEALTHY_AS_IS`. No partir archivos
para bajar LOC ni ampliar allowlists para esconder fallos deterministas.

El comentario inicial de `webauthn.py` promete rechazo de regresión genuina del
contador, pero PostgreSQL conserva high-water y marca regresión sin bloquear.
Las pruebas aceptan respuestas fuera de orden. WebAuthn §7.2 paso 22 deja la
decisión al RP: **no es por sí solo un bypass de firma**. Alinear contrato,
descripción y telemetría; no imponer rechazo automático que rompa assertions
legítimas únicamente por el comentario.

### 7. Secuencia recomendada de cierre, para un implementador GPT-6 Luna

1. **R-01 primero.** Leer ADR 0016 y writers nativos; diseñar conexión/locks;
   trasladar el probe recovery a la suite durable; observar rojo; append migration
   y owner change; probar ambos órdenes y replay. Sin UI ni grants manuales.
2. **R-02.** Diseñar handle persistido y promoción/backfill de setup; corregir
   software authenticators con handles válidos; añadir negativos y arreglar RP.
3. **R-03/R-04.** Registrar puntos de admisión y conjunto trusted de autoridades;
   implementar controles o probar restricción de instalación explícita. Cerrar
   decisiones antes de convertir «comportamiento observado» en garantía aceptada.
4. **R-05/R-06.** Corregir semántica de schemas/descripciones/replay, con tests de
   clientes y estados; no tocar policy de apply para complacer una proyección.
5. **R-07.** Completar matriz owner por owner, sin prometer revalidación universal.
6. **O-01–O-09.** Aceptar entorno y producto prometido con nombres, límites,
   responsables y artifacts reales. Gates condicionados requieren decisión
   explícita de scope; no contarlos como aprobados por exclusión silenciosa.
7. **Candidato final:** narrow proofs → `python-quality` → current-product PG18 →
   Docker suites de riesgo y conservadoras apropiadas → review semántico →
   certificación pre-push si se publica localmente → GitHub exact-candidate →
   aceptación operativa/release. No sumar subsets de SHAs distintos como PASS único.

Cada tarea debe registrar: owner, garantía, defecto falsable, boundary, inputs
trusted, esquema/error, idempotency/revision, READ/PLAN/LOCK/VALIDATE/WRITE/EMIT,
migration/ACL, rollback/roll-forward y evidencia. Nuevas migraciones desde el
head efectivo del momento; no fijar aquí el número 0034 como head eterno.

**Condición de certificación:** sin R-01/R-02 abiertos; R-03/R-04 con contrato y
pruebas coherentes; errores/autoridad/replay cubiertos en el scope prometido;
candidate CI verde incorporando las nuevas negativas; despliegue y recuperación
aceptados. La capacidad de mergear un PR verde es una decisión distinta de
autorizar un release productivo.

### 8. Cambios realizados, decisiones y estado final de esta auditoría

- Cambios versionables: este informe y su enlace en `docs/README.md`.
- Diagnósticos/artefactos locales bajo `.ci/pr137-production-audit-20261006/`.
  Se retiró únicamente el contenedor desechable creado para esta auditoría con
  `docker rm --force request-engine-pr137-audit-20261006`; su evidencia permanece.
- Ningún cambio productivo, función owner, ACL o revisión de migración modificada.
- UI y cambios preexistentes conservados; sin commit/push/merge/deploy.
- Consulta readonly al contenedor de 5432: PostgreSQL 18.6,
  `request_engine_current` en `0025_agent_credential_rotation`. No se migró.
  El head de otra base histórica no acredita el DSN que usa la aplicación.
- Decidido: no certificar producción; priorizar recuperación/handle y aceptación
  real; preservar historia inmutable y separar evidencia remota/local.
- Pendiente: todas las correcciones/gates enumeradas, consolidación de probes
  como CI durable y aceptación de la base realmente usada por la aplicación.

Modelo solicitado: [OpenAI publica `gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna).
Los intentos iniciales `openai/gpt-6-luna` recibieron HTTP 429 por límite de uso y
no produjeron reviews finales. Se completaron cuatro reviews independientes con
`openrouter/openai/gpt-6-luna`, `--agent plan --variant high`, lectura restringida
y `task/edit/bash` denegados por configuración de proceso. Sus conclusiones se
contrastaron; no se modificó configuración persistente. La herramienta `task`
de esta sesión no expone selección de modelo. No había herramienta companion o
compaction invocable expuesta; el harness gestiona la compactación.

**Estado verificado: candidato con CI existente verde y pruebas nuevas rojas.
Corrección y certificación productiva no realizadas.**

## Actualizacion del candidato 2026-10-08

### Reporte simple (para humanos)

La revisión del código posterior encontró correcciones para los seis primeros
hallazgos de este informe. La recuperación de una cuenta ya invalida su permiso
previo para adoptar la nueva política, y el acceso con passkey comprueba mejor
la cuenta, la identidad registrada y el vencimiento del intento. También se
corrigieron respuestas que podían describir mal los permisos o un consentimiento
vencido. Los fallos del 6 de octubre se conservan como evidencia del candidato
anterior; no se presentan todos como fallos todavía abiertos.

Eso todavía no certifica producción. Hay pruebas añadidas en el repositorio,
pero esta actualización documental no informa una nueva ejecución de ellas.
Falta completar pruebas de operaciones y cambios de autoridad concurrentes,
aceptar la actualización de una instalación con datos existentes, validar el
candidato final y demostrar que el entorno real funciona bajo carga, envía
correo, avisa de fallos y puede recuperarse de una pérdida de datos.

### Reporte técnico (detallado)

**Procedencia y alcance.** Inspección de `feature/admin-console` en
`1bf18997da0818f87e67cd0bb8c9e89e64f10062`, incluyendo las correcciones de
`1997505ff88924caf2438760eee5a2c2fa2beafd`. Este bloque reconcilia documentación
con código y pruebas presentes; no acredita ejecución nueva, CI exact-head,
revisión semántica final, despliegue ni aceptación operacional. Los resultados
anteriores conservan su candidato, entorno y límites originales.

| Hallazgo anterior | Corrección presente y prueba identificada | Límite que conserva la revisión |
| --- | --- | --- |
| R-01 | `0035_adoption_native_recovery_posture.py` vincula consentimiento a identidad y recovery epoch, admite ambos participantes bajo su postura nativa y deniega el consentimiento invalidado. `test_recovery_after_consent_requires_withdrawal_and_fresh_consent` en `tests/e2e/test_controller_policy_adoption_native_http.py` recorre recuperación, finalización, retirada y consentimiento nuevo. | No prueba todas las carreras recovery/apply ni suspensión del controller. No declarar la matriz adversarial completa por este recorrido secuencial. |
| R-02 | `0034_webauthn_discoverable_binding.py` persiste/backfillea handles de registro y conserva el handle de setup al promover la passkey. `test_discoverable_login_requires_the_credential_user_handle_association` en `tests/e2e/test_native_webauthn_login_http.py` cubre la asociación requerida. | La instalación limpia y el claim actual no reemplazan una prueba de upgrade poblado con credenciales registradas antes de 0034. |
| R-03 | El finalizer discoverable de 0034 revalida vencimiento después de adquirir locks. `test_discoverable_finalization_rechecks_expiry_after_identity_lock_wait` en `tests/db/test_webauthn_concurrency.py` protege ese límite. | La evidencia identificada es de finalización discoverable; no extrapolar esa carrera concreta a cada propósito de challenge. |
| R-04 | La resolución/finalización discoverable exige la autoridad nativa configurada. `test_discoverable_login_rejects_a_second_active_native_authority` en `tests/e2e/test_native_webauthn_login_http.py` cubre otra autoridad activa. | Esto no certifica la configuración RP/origin, TLS o exposición de la instalación productiva. |
| R-05 | `controller_policy_adoption_routes.py` usa `proposed_delta_does_not_restore_revoked_capabilities`; ADR 0016 explica el delta. `tests/modules/tenancy/test_controller_policy_adoption_review_projection.py` protege su interpretación. | El indicador es diagnóstico y no concede autorización para aplicar. |
| R-06 | La proyección usa estado efectivo según vencimiento, incluso en replay. `tests/e2e/test_controller_policy_adoption_http.py` comprueba detalle/replay expired, identidad del consentimiento y ausencia de application fact. | El test adelanta el vencimiento persistido; no representa espera real de 24 horas ni aceptación operacional. |

**Trabajo todavía abierto.** R-07 sigue siendo una matriz de evidencia por owner
y operación, no un defecto universal confirmado. Priorizar resource create,
assignment create/supersede/retire, availability, terms y exceptions; después
Catalog y Communications. Identificar capability/scope, lock root, admisión y
replay; probar retirada de autoridad y ambos órdenes concurrentes con efectos
durables independientes. Conservar los límites de
`architecture/administrative-transaction-authority.md`; no introducir un guard
global ni transformar namespaces de receipts en capabilities.

`current-guarantees.toml` sigue delimitando las carreras de adopción demostradas:
apply/withdraw y revocación del platform owner tienen pruebas identificadas;
suspensión del controller y otras carreras de lifecycle permanecen por demostrar.
ADR 0016 está Accepted y la adopción está implementada, por lo que el estado
actual de `auth-implementation-status.md` ya no debe describirla como propuesta.

Los gates O-01–O-09 de la sección 5 conservan sus criterios de salida: aislamiento
y TLS; upgrade poblado del entorno instalado; carga/presupuesto global; SMTP
externo; cleanup seguro si se promete destrucción; backup/restore real; alertas
y progreso; consumidor autorizado si se promete procesamiento terminal de
Requests; y certificación/revisión del candidato final. La presencia de las
correcciones no acepta ninguno de esos gates. No se actualizó una base de usuario
ni se activaron providers o cleanup en esta reconciliación documental.

### Continuación: validación numérica de recuperación

La revisión encontró otro defecto reproducido en los gates operativos: NaN e
infinito podían evitar las comparaciones de RPO/RTO o alcanzar el diagnóstico de
recuperación verificada. La corrección exige tiempos y límites finitos y no
negativos en `scripts/operations/p7_production_certification.py`,
`scripts/operations/recovery_drill_evidence.py` y el parser de
`platform_configuration/application/recovery_certification.py`. La ventana de
actualidad del gate final también debe ser finita, positiva y representable.
No cambia el schema, las migraciones ni la autoridad; cero sigue siendo válido,
y una medición sin límites aprobados sigue admitida para diagnóstico, pero no
para la certificación productiva final.

Evidencia ejecutada en Linux, Python 3.13.16 y dependencias del lockfile:

```text
uv run pytest tests/unit/operations/test_p7_production_certification.py \
  tests/unit/operations/test_recovery_drill_evidence.py \
  tests/modules/platform_configuration/test_recovery_certification.py -q --tb=short
73 passed in 0.13s
```

La primera batería antes del fix registró 38 fallos y 29 casos correctos; la
batería final añade también protección para valores enormes y controles válidos.
Las pruebas ejercitan los validadores reales y verifican que el rechazo no cree
un artifact de certificación. No prueban un simulacro ni generan una aceptación
operacional real.

La revisión independiente de consola/origen/sesión y verificación WebAuthn
ejecutó 104 casos unitarios correctos. Queda una observación estática separada:
registro de passkey normal, registro de setup y step-up todavía comprueban
caducidad antes de esperar otros locks. Debe fijarse el contrato temporal de
esas variantes y probar sus interleavings; no se reprodujo una explotación ni
se modificaron sus finalizers. El entorno actual no tiene Docker/PostgreSQL;
no se atribuye una nueva ejecución local de los tests DB ni del runner E2E.


## Continuacion de implementacion 2026-10-09

### Reporte simple (para humanos)

La revisión adicional reprodujo ocho casos en los que una passkey podía terminar
su operación después de vencer mientras esperaba a la base de datos. La nueva
corrección impide esas operaciones y revierte sus cambios parciales. También se
añadió configuración explícita del límite de conexiones: las nuevas variables
no existían antes; ahora permiten un techo menor, rechazan el exceso y el pool
se recupera. Los valores anteriores ya eran finitos.

Se ampliaron las pruebas de permisos, recuperación, suspensión y desactivación,
y se ensayó actualizar una base con passkeys y permisos existentes. Es evidencia
local del código; no acredita que una instalación real ya tenga correo, copias,
alertas, aislamiento de redes ni capacidad suficiente. Los criterios operativos
O-01–O-09 siguen pendientes de aceptación del entorno correspondiente.

### Reporte técnico (detallado)

**Cambios y decisiones.** Nueva revisión `0036_webauthn_deadline`, desde
`0035_adoption_recovery`, en
`migrations/versions/0036_webauthn_finalization_deadline.py`. Los cinco finalizers
revalidan deadline después de locks y antes de consumo; el bloque de efectos
revierte mediante subtransacción al vencer, sin cambiar firmas, ACLs, OIDs ni
lock order. ADR 0014 §10 fija el límite en el efecto del finalizer, no en el COMMIT
posterior. Roll-forward only; drenar invocaciones antiguas antes de migrar.

`platform/db/execution_budget.py::PostgresPoolBudget` acepta size 1–64 y overflow
0–64; `platform/db/session.py::create_postgres_engine` aplica los límites tanto
con presupuesto HTTP como sin él. Configuración explícita mediante
`REQUEST_ENGINE_DB_POOL_SIZE` y `REQUEST_ENGINE_DB_POOL_MAX_OVERFLOW`; defaults
5/10 preservan los anteriores de SQLAlchemy. Es un techo por engine: requiere
sumar engines, procesos y réplicas; no es presupuesto global ni rate limiting.

La matriz de 17 comandos de Booking/Catalog prueba solicitud y replay tras
retirada de Representation exacta, Principal o Party, y ambos órdenes concurrentes.
No crea una capability universal ni cambia el contrato de los guards heredados.
Las 12 carreras nuevas de adopción cubren recovery de ambos participantes,
suspensión de binding/membership del controller y global native disable de
ambos participantes. No se inventa una operación de suspensión de autoridad
nativa: no existe un owner command soportado para esa transición.

El upgrade poblado parte de 0033 y llega al head: preserva credenciales normales
y promovidas desde setup, identidades, bindings, grants/revocaciones y facts;
expira ceremonies/consent pendientes afectados por las nuevas revisiones;
conserva consumed/authentication/withdrawn y provenance histórica sin inventar
nuevos snapshots. Dos passkeys genuinas hacen login mediante un LOGIN restringido;
una assertion con firma válida y userHandle incorrecto no crea sesión. No equivale
a O-02: ese gate exige copia de la instalación real desde la revisión realmente instalada (0025).

**Entorno.** Linux, PostgreSQL 18.6 compilado de la distribución oficial. Este
sandbox solo mapea uid 0 y no tiene Docker: el build de laboratorio permite
lanzamiento root únicamente bajo una variable explícita; esa adaptación afecta
los tres controles OS de arranque de postgres/initdb/pg_ctl, no roles, RLS,
constraints ni locks. No es la imagen de producción ni evidencia Docker E2E.
Clústeres nuevos por prueba/batería, credenciales de laboratorio, runtime LOGINs
restringidos para los mecanismos reclamados; admin solo prepara fixtures/oráculos.

El runner de baseline conserva Docker por defecto y añade modo nativo explícito
`REQUEST_ENGINE_BASELINE_PG_BIN`. Inicializa otro clúster limpio, SCRAM y loopback,
instala 0001 dos veces y ejecuta los mismos catálogos/integridad/identidad. No
reescribe baseline ni migra datos de usuario. El wrapper local inicia vía Bash;
los datos temporales se alojan fuera del árbol sincronizado para evitar errores
de retirada de `.rsync-tmp` después de pruebas correctas.

**Evidencia focal ejecutada**, en `.ci/readiness-20261008/`:

| Prueba | Resultado y límite |
| --- | --- |
| WebAuthn antes, 0035 | 8 FAIL / 7 PASS; contender COMMIT anterior al oráculo evita rollback accidental de resultados defectuosos |
| WebAuthn después, 0036 | 50 PASS en 27,58 s; ACL/OID/security/search_path idénticos; downgrade rechazado |
| Pool antes, source `cbf0478c` | 2 FAIL: admite tercera conexión pese al techo configurado |
| Pool después, asyncpg/psycopg | 6 PASS en 2,66 s, incluyendo statement/lock timeout y liberación/reutilización |
| Booking/Catalog autoridad | 204 PASS en 77,32 s; quitar temporalmente guard produce FAIL esperado |
| Catalog offering policy/Communications existentes | 22 PASS en 8,15 s |
| Adopción, familia completa | 20 PASS en 16,03 s; runtime roles y bloqueos observados |
| Upgrade 0033→head | 1 PASS en 2,43 s; credenciales genuinas y oráculos durables |

Los primeros runs de deadlines/matriz acabaron con error de cleanup del wrapper
posterior al pytest; el directorio detenido se retiró después. No se presentan
sus códigos globales como PASS. La validación general posterior detectó 16 errores
Pyright en tests nuevos (imports privados/lista sin tipo); se corrigieron nombres
compartidos y tipos, sin eliminar pruebas ni suprimir el chequeo.

**Pendiente.** Registrar el resultado de la batería canónica completa y del
candidato estable; CI remoto exact-head, revisión/merge y O-01–O-09 siguen sin
aceptación. La retención/rate de emisión de challenges discoverable sigue siendo
un asunto operativo abierto: el techo de conexiones no resuelve crecimiento de
filas ni abuso distribuido. Requests requiere definir su consumidor si se promete
resultado terminal automático. No se publicaron estos cambios ni se activaron
SMTP/OpenBao/cleanup/restore de una instalación real.


Revisión independiente posterior: no se confirmó un defecto en rollback,
lock protocol, ACLs de 0036 ni techo del pool. Se precisó que los defaults
anteriores ya eran finitos y que el worker sin presupuesto HTTP conserva el
pool acquisition timeout de SQLAlchemy, no un driver connection timeout.
El modo baseline nativo ahora conserva el directorio y falla si `pg_ctl stop`
falla. Una inyección real de stop fallido verificó código 1, clúster vivo
conservado y parada posterior exitosa (`native-cleanup-fault/result.txt`).

`python-quality-final` terminó con 12 pasos PASS: 203 architecture, 1133 unit
(una advertencia de deprecación) y 770 modules. El primer runner PostgreSQL
completo se detuvo con 476 PASS/2 FAIL en principal-authority: dos clientes
HTTP locales de pruebas heredaban un proxy SOCKS del sandbox sin `socksio`.
Se añadió `trust_env=False` solo a esos clientes de loopback, preservando
fences/locks/oráculos y el cliente productivo. La repetición completa se inició
en un clúster nuevo, con evidencia separada `current-product-final`.


La ejecución `current-product-final` pasó 20 paquetes completos, incluidos
478 casos de principal-authority, pero fue interrumpida durante `tests/e2e` y
no produjo `proof-execution.json` ni un exit global verificable. No se presenta
como batería completa aprobada. La continuación reprodujo un fallo de
`test_http_runtime_factory_starts_under_real_app_login`: otro cliente loopback
heredaba el proxy SOCKS del sandbox. Corrección test-only `trust_env=False`;
antes 1 FAIL/6 PASS, después 7 PASS en 7,25 s (PG18.6, `luna-runtime.xml`). No
se cambió la configuración de proxy del runtime productivo ni se añadió una
dependencia opcional para hacer pasar el cliente local.

La segunda revisión independiente de upgrade/matriz/lifecycle no identificó
oráculos vacíos ni preparación previa del resultado esperado. Se corrigió una
frase: el `userHandle` no está firmado; el caso negativo presenta una assertion
con firma válida y un `userHandle` incorrecto. Se corrigió también el anchor
ASCII del enlace al bloque actual. La nueva batería `current-product-complete`
registra explícitamente su código de salida aparte del log y JUnit; su resultado
final debe verificarse antes de declarar cierre local.


### Cierre de validación local completa

La batería `current-product-complete` **terminó con exit 0** sobre código y pruebas
estables de `7ca79bca922b54ba51cdf23be090792e473f50c3`. Las correcciones del cliente
TCP privado quedaron aplicadas antes de iniciar collection de `tests/e2e`.
Base remota reconfirmada por `git fetch`:
`1f0d3fcc5fa537ef6f014d66e24effd77a1ad14d`; feature remota aún
`1bf18997da0818f87e67cd0bb8c9e89e64f10062`. La documentación final posterior no
cambia código, pruebas, migraciones ni dependencias.

```text
bash ../run-pg18-lab.sh current-product-complete none \
  env REQUEST_ENGINE_BASELINE_PG_BIN=/workspace/scratch/c9098fcf9926/pg18-runtime/bin \
  CURRENT_PRODUCT_CI_ARTIFACT_DIR=.ci/readiness-20261008/current-product-complete \
  bash scripts/ci/run_current_product.sh
```

Entorno: Linux, Python 3.13.16, PostgreSQL 18.6 del laboratorio descrito arriba,
dependencias del lockfile. No Docker ni servicios productivos. Evidence:
`current-product-complete-run.log`, `current-product-complete-exit.txt`, los JUnit,
`proof-execution.json` y `stop.log` en `.ci/readiness-20261008/`.

| Resultado final | Evidencia |
| --- | --- |
| Runner canónico completo | 24 paquetes; 1676 pruebas; 0 failures, 0 errors, 0 skipped; exit 0 |
| E2E in-process/runtime PostgreSQL | 484 PASS; no sustituye Docker/ingress externo |
| Principal/authority/WebAuthn/upgrade | 478 PASS |
| Semantic commands, incluida matriz nueva | 317 PASS |
| Baseline independiente | 0001 instalada dos veces; catálogos de schema/roles/seed equivalentes; identidad local distinta |
| Migración multibase | Segunda base alcanza 0036 con roles compartidos auditados |
| Mapa de ejecución | 389 archivos ejecutados; 79 garantías con pruebas mapeadas ejecutadas; gaps=[] |
| Cleanup laboratorio | Servidor detenido; wrapper y comando exterior exit 0 |

El segundo cliente TCP local, en
`tests/e2e/test_platform_control_runtime_factory.py`, también reprodujo la
interferencia del proxy. `trust_env=False` corrige solo el cliente de loopback:
10 casos del archivo PASS en 13,17 s, además de su inclusión en los 484 E2E del
runner final. Los dos checks de servidores conservan startup con LOGINs reales,
readiness y rechazos de privilegios; no reemplazan TCP por mocks.

**Estado local:** vencimiento de los cinco finalizers corregido y ejecutado;
matriz de 17 operaciones y carreras de adopción ejecutadas en sus scopes
explícitos; upgrade poblado 0033→head ejecutado; pool finito configurado y
verificado con ambos drivers; calidad y revisión independiente completadas.
Los candidatos de mantenibilidad reportados por certificación son señales de
revisión, no defects reproducidos ni aprobación automática de producción.

**Estado de producción:** continúa **NO CERTIFICADO**. O-01–O-09 no quedan
aceptados por estos resultados. Faltan GitHub CI/review del nuevo HEAD, la copia
del entorno real desde 0025, presupuesto agregado y carga/rate/retención de
challenges, SMTP externo, cleanup admitido/scheduled si se promete destrucción,
backup/restore sin fuente y alertas recibidas por el operador. Requests necesita
su consumidor y autoridad acordados si se promete resultado terminal automático.
No se desplegó, publicaron cambios, enviaron mensajes ni tocaron datos reales.


## Candidato operativo sin instalación (2026-10-09)

El usuario confirmó que todavía no hay una instalación. Por tanto, no existe
un proveedor SMTP, host de restauración, receptor de alertas ni red productiva
que pueda aceptarse con evidencia real. Las pruebas del repositorio y del
laboratorio no fabrican esas aceptaciones.

El árbol certificado local `99b9be0da5390c8d3af091fe16499219b736371c` quedó
publicado en `origin/feature/admin-console` mediante el commit
`a2579c0e4a5238dab6756b5f01c41902e6c9a9e5`. El transporte autenticado de GitHub
creó un SHA diferente al checkpoint local `8dd23ac4`; se comparó el árbol exacto,
sin omisiones. El CLI de Git carecía de credenciales para escribir. Los
checkpoints locales se conservaron en una rama `tmp/` sin PR. No se hizo merge.

El siguiente candidato añade:

- TTL WebAuthn entero entre 1 y 900 segundos; no admite booleanos, flotantes,
  NaN ni infinito. El default sigue siendo 300 segundos.
- Retención manual acotada en `0037_webauthn_retention`, sin reescribir 0001:
  siete días por defecto, mínimo 24 horas, máximo 90 días; lote máximo 1000.
  No elimina desafíos vivos ni consumos recientes, credenciales, sesiones,
  auditoría o secretos. Usa `SKIP LOCKED`, índice de expiración y roles separados
  `request_webauthn_retention` / `request_webauthn_retention_definer`. El mínimo
  `UPDATE(id)` del definer sirve al requisito PostgreSQL del bloqueo; la función
  no actualiza ese campo. Roles preexistentes inseguros deben abortar el upgrade.
- Admisión de POST de autenticación nativa/setup a 120 intentos por minuto por
  proceso, configurable entre 1 y 10000, antes de body/hashing/SQL; 429 y
  `Retry-After`. GET de sesión y probes quedan fuera. Réplicas y reinicios
  requieren controles agregados de ingress; esto no certifica rate global.
- Probe de carga con destino/ruta explícitos, sin redirects ni proxy heredado,
  TLS verificado, solicitudes/concurrencia/tiempo/cuerpo finitos y latencia hasta
  el cuerpo completo. Truncamiento, cuerpo lento, exceso y compresión inesperada
  cuentan como error; no se guardan bodies ni cabeceras sensibles.

### Evidencia de carga real de laboratorio

La prueba siguiente pasó en PostgreSQL 18.6 y Python 3.13.16:

```bash
bash ../run-pg18-lab.sh runtime-load-rate head uv run pytest \
  tests/e2e/test_http_load_probe_runtime.py -q -s
```
 El servidor Uvicorn usó TCP y un LOGIN runtime real sin elevación,
pool size 1 + overflow 1; los datos son artificiales. Presupuesto de p95 5000 ms
solamente para el laboratorio, no un SLO aprobado.

| Fase | Resultado independiente |
| --- | --- |
| 200 readiness GET, concurrencia 2 | 200 respuestas 200; p95 44,32 ms; cero errores |
| 100 opciones WebAuthn POST, concurrencia 2 | 100 respuestas 200; p95 47,98 ms; cero errores |
| Otras 50 opciones, misma ventana | 20 respuestas 200, 30 respuestas 429; el probe devuelve `budget_exceeded` |
| Estado autoritativo | Exactamente 120 desafíos pendientes persistidos; ninguna sesión emitida |

La medición previa con concurrencia 8 registró 136 respuestas 200 y 64 respuestas
503 (32% de errores). Ese resultado se conserva como rechazo bajo presión,
no como capacidad aceptada: había límites de probes y conexiones inferiores a
la concurrencia. La medición por sí sola no identifica cuál causó cada rechazo.
La fase nominal no borra esa limitación ni mide CPU/RSS, carga multi-réplica,
hashing sostenido, duración extensa o cardinalidad productiva.

### Operaciones que siguen sin aceptación real

| Área | Estado y siguiente evidencia necesaria |
| --- | --- |
| Correo | Runbook `operations/p7-smtp-production-acceptance.md`; faltan proveedor, secreto, dominio/TLS y entrega a buzón real, fallo ambiguo y throttling |
| Restauración | Runbook `operations/p7-disaster-recovery-drill.md`; falta restaurar PostgreSQL + OpenBao desde copia off-host sin fuente y medir RPO/RTO, con outbound fence |
| Alertas | Contrato/runtime probado; faltan destino y recepción por un responsable al inducir fallos reales |
| Aislamiento | Docker E2E prueba su red de laboratorio; faltan host/ingress y pruebas negativa pública→control/DB, TLS/proxies de la instalación |
| Retención | CLI lista para invocación explícita; faltan LOGIN/secret dedicados y schedule operativo. Su índice requiere planificar locks/drain de autenticación al migrar una tabla grande |
| Capacidad | Carga de laboratorio ejecutada; faltan presupuesto agregado por proceso/réplica, ingress compartido y carga del producto prometido |

Las nuevas pruebas deben quedar incluidas en los runners canónicos y en el mapa
de garantías. El CI del árbol anterior no certifica estos cambios nuevos:
se requiere publicar el nuevo árbol y esperar todos sus workflows de exact-head.
El estado sigue siendo **preproducción; no certificado para producción**.


El CI de `a2579c0e` terminó con los cinco workflows en `success`: CI
(run 37965587545, incluidos calidad, observabilidad, historia V2 y PostgreSQL
actual), Docker E2E (37965587504), configuración P7 (37965587550), Coolify
(37965587438) y recuperación simulada (37965587418). La revisión adversarial
independiente del árbol nuevo confirmó cerrado el hallazgo de roles con ACL
excesivos tras las pruebas de upgrade aislado. La batería enfocada final pasó
46 pruebas PostgreSQL y 54 unitarias; la multibase final pasó con los roles
exactos en ambas bases. Esto no reemplaza el CI propio del siguiente candidato.
