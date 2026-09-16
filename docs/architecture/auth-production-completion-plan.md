# Plan ejecutable de cierre de identidad, ergonomía y producción

Fecha: 2026-09-14. Branch de referencia: `cohesion/system-optimization`.

Estado: **plan de implementación propuesto, no certificación ni autorización de
despliegue**. El usuario pidió un handoff suficientemente detallado para que otro
agente pueda completar el trabajo. Este documento explica la solución recomendada,
sus límites, decisiones pendientes, orden, pruebas y condiciones de salida.
Bloque A (outcome de enrollment, revisión0041), el plano tenant de B2
(continuidad con vía autenticable, revisión0042), B1/B5 (capabilities de
provisioner, proyección de lectura y ciclo de vida revisionado con auditoría
privada append-only, revisión0043), B3 (gate de topología, revisión0044) y C
(recuperación gobernada con entrega segura por puerto técnico, revisión0045)
están implementados y validados localmente; su evidencia vive en
`auth-implementation-status.md`. Dentro de D, la proyección de lectura de
bindings (`identity.binding.read`, `identity_binding_list`/`identity_binding_get`)
y el ciclo de vida local de binding (`identity_binding_suspend`/`_reactivate`/
`_revoke` vía `identity.bind`, revisión0046, con orden de locks root-antes-de-fila
y la prueba de carreras B-02) están implementados y validados localmente; el disable
global D3 de identidad nativa (`platform.identity.disable`, revisión0047, gate
EXCLUSIVE con `lock_timeout` acotado, reader privado y continuidad multi-tenant)
está implementado y validado, incluida su prueba HTTP privada. El linking
self-service D2 está implementado en modo native-only (revisión0048 de frescura de
reautenticación y revisión0049 de intents y binding para el Principal existente);
la prueba OIDC de doble posesión queda fuera de alcance mientras no exista una
conexión OIDC. E3, F y G tampoco existen.
Las decisiones D1–D6 fueron ratificadas por ADR 0013; cada bloque todavía necesita
su contrato propio donde el plan lo exige (por ejemplo, el inventario completo de
writers y la prueba de inversión de locks de D5).

## 1. Objetivo y precedencia

Entregar un Request Engine operable desde cero sin IdP externo, con humanos,
agentes e integraciones de primera clase, permisos explícitos y revocables, y una
API que un developer o agente pueda explorar y usar sin SQL de configuración.
Una identidad autenticada nunca fabrica Principal, grants ni Representation.

El cierre tiene tres dimensiones distintas:

1. **Producto:** los journeys requeridos existen, incluidos recuperación y
   administración segura. No basta con tener primitivas internas.
2. **Evidencia:** pruebas capaces de fallar, PostgreSQL real, HTTP real y CI del
   commit exacto; no usar un verde anterior para código posterior.
3. **Operación:** configuración, secretos, delivery, ingress, backup/restore,
   migraciones y aceptación humana del entorno elegido.

Este plan no reemplaza garantías ni convierte propuestas en contratos aceptados.
Precedencia: `system-optimization-mode.md`, `continuous-evolution-policy.md`,
`../testing/current-guarantees.toml`, contratos propietarios y ADR aceptados.
En identidad, leer juntos `identity-provider-and-staff-provisioning-plan.md` y
`principal-agent-and-provisioning-authority-model.md`; el segundo enmienda los
slices del primero. No asignar trabajo por número de slice sin leer esa enmienda.
HTTP y tools obedecen docs15/16; ownership y conexiones obedecen docs07/09/10/13.

OIDC sigue siendo opcional. Una instalación native-only debe completar el cierre
sin Google, WorkOS, Clerk, JWKS remoto ni un proveedor B2B. Un adaptador B2B externo
completo se difiere salvo requerimiento explícito; no confundirlo con las
INTEGRATION Principals nativas que sí son parte del producto actual.

## 2. Punto de partida verificado y trabajo que NO debe repetirse

El detalle y artefactos viven en `auth-implementation-status.md`.

| Superficie actual | Evidencia/limitación |
| --- | --- |
| Native enrollment, login, rotación, logout y primitivas de recovery/disable | Existen; administración gobernada incompleta |
| `POST /auth/native/password:recover`, `nativePasswordRecover` | Consumo HTTP de prueba de un solo uso; no emisión/entrega pública |
| 0039 | Orden identidad antes de recovery intent; regresión de deadlock probada |
| 0040 | Suspensión de autoridad en lecturas de credenciales y mutaciones positivas; SHARE antes de identidad; revocar sigue permitido |
| Provisioning privado | Factory separada `create_platform_control_app`; no convertirla en una puerta pública |
| Staff, agents, integrations | Ciclos y autoridad actuales, readers y pruebas; no reimplementar en un nuevo servicio genérico |
| `/v1/me/authority` | Relaciones actuales propias; no equivale a acceso efectivo a todo recurso |
| Onboarding | `/v1/onboarding/readiness`, `onboarding_read`; compone supply, no prueba identidad/control |
| Catálogo | Proyección autorizada de operaciones; no sustituye validación propietaria al invocar |
| CI local al checkpoint | 816 pruebas PostgreSQL/E2E, 18 XML, 300 archivos ejecutados, gaps vacíos; calidad12/12; 821 unit/module en Linux |
| Compose actual | Solo PostgreSQL; no es una topología de producción de API/worker/control plane |

Limitaciones importantes del checkpoint:

- Árbol sucio; no GitHub exact-head ni certificación de publicación de ese árbol.
- App DB `request_engine` en5432 seguía en0037; test DB local ya estaba en0040.
- El runner sobre5432 rechazó membresías E2E preexistentes del clúster. No se
  borraron ni relajaron controles; se completó el runner en un clúster aislado.
- Enrollment bajo autoridad suspendida devuelve409 `native_identity_already_exists`.
  Es seguro en rechazo, pero comunica un hecho falso y una recuperación incorrecta.
- `assert_other_tenant_controller` de0019 cuenta membership/grants de control;
  no asumir que eso prueba una vía autenticable alternativa completa. Hay que
  revisar la definición efectiva al HEAD antes de extenderla.
- Los scripts locales de mutación/upgrade en `.ci/` son evidencia auxiliar,
  no pruebas durables adicionales de la lane.

### Mapa de código inicial

Rutas existentes, relativas a la raíz del repo:

```text
src/request_engine/platform/security/native_human_auth.py
src/request_engine/platform/db/native_human_auth_store.py
src/request_engine/platform/security/native_session.py
src/request_engine/platform/security/capability_registry_identity_authority.py
src/request_engine/entrypoints/http/native_auth.py
src/request_engine/entrypoints/http/native_auth_errors.py
src/request_engine/entrypoints/http/platform_control_app.py
src/request_engine/entrypoints/platform_bootstrap_cli.py
src/request_engine/modules/tenancy/api/native_platform_provisioning.py
src/request_engine/modules/tenancy/api/staff_membership_routes.py
src/request_engine/modules/tenancy/api/staff_membership_reads.py
src/request_engine/modules/tenancy/contracts/onboarding_readiness.py
src/request_engine/modules/onboarding/README.md
src/request_engine/modules/onboarding/application/readiness.py
src/request_engine/modules/onboarding/api/router.py
scripts/ci/run_current_product.sh
scripts/db/prove_multidatabase_migration_compatibility.py
```

Buscar con `rg` los callers y AGENTS cercanos antes de editar. No asumir que este
mapa congela la estructura. No crear carpetas vacías por ceremonia arquitectónica.

## 3. Decisiones que se deben registrar antes de implementar seguridad nueva

Resolverlas en un ADR/contrato aceptado, con dueño y fecha. El agente puede
implementar A (ergonomía) y preparar evidencia mientras se resuelven B–F, pero no
habilitar recovery global, linking o break-glass basándose en una suposición.

| ID | Recomendación concreta | Decisión/aceptación necesaria |
| --- | --- | --- |
| D1 Recuperación global | Control plane privado; HUMAN con autoridad de seguridad explícita; caso y aprobación por otro HUMAN; nunca basta ser provisioner de tenants | Dueño acepta doble control, quién verifica titularidad y cómo se obtienen inicialmente esas autoridades |
| D2 Entrega del secreto | Canal previamente verificado y secret store separado con staging/TTL; ningún reset secret en audit, outbox ordinario o respuesta administrativa | Elegir secret store y adaptador de entrega reales; política para resultados ambiguos y evidencia de titularidad |
| D3 Linking v1 | Self-link a su Principal mediante pruebas frescas de ambas identidades; no merge por email ni linking administrativo arbitrario | Aceptar esquema de prueba de posesión, frescura y proveedores/facetas admitidos |
| D4 Continuidad | Siempre conservar al menos un controlador efectivo con una vía autenticable; excepciones solo en recuperación de plataforma explícita | Ratificar predicado exacto tenant/platform y semántica del kill switch de autoridad |
| D5 Serialización | Gate transaccional de topología antes de locks actuales, compartido para cambios locales y exclusivo para operaciones globales | ADR, inventario completo de writers y pruebas de ausencia de inversiones; no aplicar solo a endpoints nuevos |
| D6 Operación | Native-only primero, private control plane separado, configuración fail-closed | Entorno, DNS/TLS/ingress, RPO/RTO/SLO, gestor de secretos, delivery, operadores y aprobación del despliegue |

Defaults propuestos para concretar las pruebas, ajustables solo en el contrato:
prueba de reautenticación máximo5 minutos; recovery proof máximo30 minutos;
aprobación máxima24 horas; paginación default50/máximo100; referencias de caso
máximo400 caracteres y siempre sin texto clínico, PII ni credenciales.
Son propuestas, no valores ya implementados ni requisitos de un estándar.

No hay seguridad de producción si una instalación con un solo operador activa
doble control ficticio. En ese caso: añadir un segundo operador autorizado o
aceptar/documentar un mecanismo offline de recuperación de despliegue. No crear
un `force=true`, una capability universal o un usuario de soporte omnipotente.

## 4. Orden de ejecución y fronteras del trabajo

```text
P0 inventario y contrato de cierre
  -> A outcome de enrollment
  -> B continuidad + serialización + auditoría + ciclo de operadores
       -> C recovery gobernado + entrega
       -> D bindings + dual-proof linking + disable global
  -> E políticas existentes + onboarding + diagnósticos
  -> F journeys adversariales integrados
  -> G aceptación operacional + publicación exact-head
```

C y D pueden diseñarse por separado, pero comparten B; no hacer migraciones
concurrentes ni dos ramas merge-ready. Por defecto un implementador en la sesión;
si se autorizan subagentes después, delegar revisión/lecturas o áreas disjuntas,
no la misma BD ni el contrato de locks. Cada bloque deja código, pruebas,
documentación y un handoff corto con comandos/resultados/pendientes.

### P0 — Verificar el mundo antes de editar

1. Leer AGENTS y contratos propietarios; `git status`, branch, HEAD, fetch de
   `origin/development` y comprobar `.github/development-integration-lane`.
   Preservar cambios locales. Si cambió development, reconciliar según política;
   no resetear ni crear un segundo carril. No commit/push/PR/merge por inferencia.
2. Inventariar HEAD Alembic y DB real, PostgreSQL18, roles efectivos, configuración
   de factories y las rutas/operationIds existentes. Usar SQL de catálogo sin
   imprimir credenciales. No confundir `.env` con el entorno efectivo del proceso.
3. Reproducir selectivamente el checkpoint si cambió el source; la evidencia
   histórica no se hereda. Registrar hashes/commit y estado dirty del source.
4. Crear una matriz de requisitos con IDs A–G abajo; cada fila tiene dueño, código,
   prueba, lane y estado `pendiente/implementado/validado/bloqueado`.
5. Para D1–D6 pendientes, documentar bloqueo preciso; no inventar aprobación.

Salida P0: inventario verificable y decisiones ratificadas para el bloque a iniciar.

## 5. A — Outcome honesto de enrollment

**Riesgo:** falso409 ante proveedor no disponible. No arreglarlo mediante un
precheck fuera de la transacción: la autoridad puede suspenderse después.

Diseño recomendado, sin cambiar la firma SQL de la función existente:

1. Añadir migración posterior al HEAD real (0041 solo si sigue libre). Reemplazar
   `request_auth.create_native_identity` mediante cuerpo explícito. Conservar
   propietario, SECURITY DEFINER, search_path, ACL y authority SHARE de0040.
2. Contrato SQL trivalente documentado: `true=created`, `false=duplicate`,
   `NULL=authority_unavailable` para autoridad ausente, suspendida o de otro kind.
   Rechazar antes de tocar identidad/credencial. No cambiar0001–0040 aplicadas.
3. En `NativeHumanAuthStore.create_identity`, devolver un enum tipado
   `NativeEnrollmentOutcome` con esos tres casos. Adaptador interpreta el scalar
   exacto; no usar `bool(result)` porque colapsa NULL y false. Un valor inesperado
   es fallo interno cerrado, no duplicado ni éxito.
4. Servicio transforma DUPLICATE en `NativeIdentityAlreadyExists` y UNAVAILABLE
   en `NativeEnrollmentUnavailable`. No incorporar selección de proveedor desde
   el body: la autoridad sigue viniendo de configuración confiable.
5. HTTP conserva201/409/422 existentes y añade503
   `native_enrollment_unavailable`, mensaje genérico, no-store/no-cache,
   `resolution=operator_intervention`, `retryable=false`; no sugerir login ni
   reintentar ciegamente. No revelar si la autoridad está ausente o deshabilitada.
6. Actualizar OpenAPI, error inventory, fakes del store, ejemplos y pruebas.
   Mantener path/operationId actuales. No proyectar enrollment como tool de agente.

Compatibilidad: binario viejo seguirá interpretando NULL como fallo409, no éxito.
Binario nuevo requiere la migración para distinguirlo; declarar schema mínimo de
la superficie antes de dar readiness verde. No probar disponibilidad llamando a
una función de escritura. Upgrade DB antes de binario; rollback lógico roll-forward.

Pruebas A: activo nuevo201, activo duplicado409, suspendido/ausente/wrong-kind503,
password inválido422, suspensión que gana carrera503 sin filas nuevas y auth que
gana primero201 antes de suspensión. Comparar hechos tras commit. Restaurar la
función anterior en scratch debe hacer fallar la prueba503. Cierre: unit+HTTP+DB,
privilegios/upgrade poblado y lanes canónicas verdes.

## 6. B — Base segura compartida

### B1. Separar la administración global de la local

- Tenancy posee policy de Principal, binding, membresía, control y provenance.
  `platform/security` conserva credenciales, autenticación y mecánica de proofs.
  No mover decisiones de administración al store técnico.
- Una identidad nativa es global a su autoridad y puede autenticar varios tenants.
  `staff.manage_membership` permite quitar acceso local, no resetear su password
  global. `organization.provision` tampoco autoriza recuperación global.
- La policy global se expone en el control plane privado mediante operaciones
  propietarias de Tenancy con `PlatformActorContext`; no en la API tenant.
- Usar capabilities existentes cuando su semántica encaje. `platform.identity.recover`
  e `identity.bind` ya están registradas pero no son superficies completas.
  Activarlas exige readers, commands, runtime y pruebas; no basta cambiar un flag.
- Capabilities nuevas propuestas: `platform.identity.read`,
  `platform.identity.recovery_approve`, `platform.identity.disable`,
  `platform.provisioner.read`, `platform.provisioner.manage_lifecycle`,
  `identity.binding.read`, `identity.link_self`. Reusar `identity.bind` para los
  comandos de ciclo local de binding; no crear una segunda capability de gestión
  con la misma autoridad ni dejar el predicado de continuidad contando un permiso
  que no habilita ninguna operación real.
  Registrar owner/plano/riesgo/exposición en el registry actual, no una segunda lista.
- Cambios de autoridad: riesgo AUTHORITY_CHANGE, HUMAN explícito; AGENT,
  INTEGRATION y SYSTEM no adquieren estas facultades por tools, delegación o headers.
  La ejecución técnica de un delivery worker es una excepción estrecha por ticket,
  no un Principal con facultad genérica de administrar identidades.

### B2. Continuidad que incluye una vía de autenticación

Un controlador alternativo válido requiere, en el estado posterior propuesto:

1. Principal activo en el plano correcto y membership activa si es tenant.
2. Grants efectivos de control actuales: partir del conjunto actual
   `staff.manage_membership`, `staff.manage_authority`, `identity.bind`; ratificar
   cualquier cambio. No contar un grant temporal como control permanente.
3. Al menos un binding activo cuya autoridad esté activa y corresponda al kind
   de sujeto. Para native: identidad activa y credencial password activa. Para
   externo: configuración/autenticador admitido; no prometer disponibilidad de
   red ni que el proveedor no revocó un token que RE no puede observar.
4. Ninguna revocación/suspensión de la operación propuesta elimina esa vía.

El predicado es propiedad de Tenancy, reutilizable por comandos y reader. La parte
técnica de credential validity se publica como booleanos acotados, no verificadores
ni acceso directo nuevo a tablas de credenciales. El read puede orientar al usuario;
solo el check dentro de la transacción autoritativa permite la escritura.

Deshabilitar una identidad global requiere enumerar sus tenants afectados con una
frontera privada mínima. No exponer esa enumeración al admin de un tenant. Todos
los tenants deben conservar control o la operación completa debe fallar, sin
estado parcial. Hacer dry-run no reserva el resultado; ejecutar revalida.

Autoridad suspendida y native identity disabled son distintas: la primera es
reversible y puede dejar sesiones/proofs válidos al reactivarse; la segunda es
terminal bajo el contrato actual. No añadir `enable identity` para resucitarla.
Un kill switch de proveedor puede deliberadamente cortar todo login; requiere
un camino de despliegue/break-glass separado, auditable y aceptado en D4.

### B3. Locks: cerrar la carrera de descubrimiento de tenants afectados

Solo ordenar UUIDs de los bindings encontrados NO resuelve un binding nuevo que
aparece después de enumerarlos. Tampoco introducir autoridad→organización en un
writer nuevo mientras los writers existentes toman organización→autoridad.

Recomendación para v1, sujeta al ADR D5:

- Introducir un **gate PostgreSQL advisory transaccional de topología de identidad**
  con clave fija y namespace registrado, scoped a la BD. SHARE al entrar en todo
  cambio local que altere bindings/control/reachability; EXCLUSIVE al entrar en
  disable global o modificación global de autoridad. Adquirirlo antes de cualquier
  lock de fila. Las lecturas ordinarias y booking no lo adquieren.
- Inventariar e incorporar TODOS los writers: bootstrap, provisioning nativo,
  staff activate/suspend/revoke/authority-replace, binding/link, cambios de grants
  de control, lifecycle de provisioners y cambios globales. Un trigger tardío que
  toma el gate después de locks de fila no resuelve la inversión.
- Dentro de SHARE mantener/revisar el orden propietario actual. Dentro de
  EXCLUSIVE enumerar tenants/principals afectados y validar sobre estado estable;
  authority→native identity→credential/intent para las primitivas auth. Los cambios
  locales quedan fuera hasta commit. Native login/rotation no adquieren locks
  de negocio, por lo que no deben esperar por una operación de red con el gate tomado.
- Auditar los callers existentes que ya toman principal/membership antes de
  `lock_credentialed_native_identity`; añadir el gate al inicio real del comando,
  no en el último helper. Reusar el lock root tenant actual para mutaciones locales
  y probar A-revoca-B/B-revoca-A. No asumir que el helper0019 basta por sí solo.
- No otorgar DML directo para saltarse este protocolo. Backstops estructurales,
  RLS y la superficie de comandos restringida permanecen. Documentar todos los
  caminos privilegiados de mantenimiento que podrían eludirlo.

Tradeoff honesto: EXCLUSIVE pausa temporalmente cambios de autoridad de otros
tenants, aunque no booking ni login ordinary. Es una opción conservadora para
operaciones globales raras. Medir contención y poner límites/timeout; no declarar
escalabilidad ilimitada. Si no es aceptable, diseñar locks por identity + retry de
conjunto versionado con prueba equivalente ANTES de implementar otra topología.

### B4. Transacción, revisión, idempotencia y auditoría

- Cada semantic command usa un Session y una transacción. No invocar el store
  actual que abre otra transacción dentro de un comando que debe ser atómico.
  Añadir un port transaccional estrecho/bound adapter donde haga falta, reusando
  las primitivas SQL. No convertir toda la lógica en un procedimiento gigante.
- Commands no secretos requieren Idempotency-Key; scope por actor/plano/tenant/
  operación, fingerprint de intent normalizado, sin proofs. Replay primero
  revalida autoridad actual; key distinta no duplica transición terminal.
- Body usa `expected_revision >= 1` del agregado; resolver de nuevo la revisión
  de autoridad del actor. No aceptar un actor revision suministrado como confianza.
  Stale409 con `refresh_and_retry`; refresh no garantiza permiso actual.
- Auditoría append-only en la misma transacción: actor, executor, sujeto objetivo,
  acción, reason code, caso externo opaco, revisiones antes/después y correlation.
  No token, verifier, login handle, datos clínicos ni notas libres. Para hechos
  globales crear frontera de auditoría privada correcta; no inventar un tenant
  ni usar outbox de negocio como almacén de eventos de credenciales.

### B5. Ciclo de operadores/provisioners

Completar list/get y suspend/reactivate/revoke del provisioner ya creable. Preservar
provenance y grants históricos; reactivar no concede nuevas capabilities. Revocar
no elimina organizaciones previamente provisionadas. Usar el plano PLATFORM,
revisión e idempotencia, y protección del último controlador de plataforma.
La capability de crear provisioners no debe conceder automáticamente facultad de
resetear sus identidades ni gestionar a quien lo creó.

## 7. C — Recuperación administrada y entrega segura

### C1. Modelo y API recomendados

Tenancy posee un agregado `IdentityRecoveryCase`, no el módulo genérico Requests:
es un workflow de seguridad, no una nueva demanda de negocio del cliente.
Persistir target native identity, iniciador, aprobador, evidencia opaca de
titularidad, destino verificado por referencia, revisiones capturadas, estado,
expiry, revision y vínculo al recovery intent. Nunca almacenar raw secret ahí.

Estados propuestos:

```text
requested -> approved -> issued -> consumed
    |           |          |
    +-----------+----------+--> revoked / expired
```

`delivery_status` es independiente: pending/sending/delivered/unknown/failed.
Staging ocurre en el secret store mientras el caso sigue approved; no inventar
un estado autoritativo staged sin una transición y reconciliación durables.
Entregado no significa consumido; `unknown` no significa que el usuario no recibió
el mensaje. Reconciliar consumo con la transición real de recovery intent, no un
contador duplicado que pueda divergir.

API privada nueva propuesta, owner Tenancy; prefixes a reconciliar con el router
privado existente antes de congelar OpenAPI:

| Método y path | operationId propuesto | Capability | Entrada/salida |
| --- | --- | --- | --- |
| POST `/v1/platform/identity-recovery-cases` | `platform_identity_recovery_case_create` | `platform.identity.recover` | target UUID, reason enum, evidence_ref, delivery_destination_ref → 201 case view |
| GET colección / `/{case_id}` | `platform_identity_recovery_case_list` / `_get` | `platform.identity.read` | cursor/limit y filtros acotados → vistas sin secretos |
| POST `/{case_id}:approve` | `platform_identity_recovery_case_approve` | `platform.identity.recovery_approve` | expected_revision → vista actual |
| POST `/{case_id}:issue` | `platform_identity_recovery_case_issue` | `platform.identity.recover` | expected_revision → 202 con case/delivery state; nunca token |
| POST `/{case_id}:revoke` | `platform_identity_recovery_case_revoke` | `platform.identity.recover` | expected_revision, reason → vista terminal |

Un case view contiene ID, target ID, estado, delivery state, expiry y revision;
solo el operador global autorizado ve el target. No exponer email/destino completo,
secret-store URI, proof, hash, provider response ni otros tenants. Reads no-store,
paginación50/100, cursor opaco scoped. Todas las mutaciones son AUTHORITY_CHANGE,
no tools. UI administrativa puede usar la misma API, no un bypass.

Approve exige HUMAN distinto del solicitante, authority fresca y política de
titularidad D1 satisfecha. Un texto `evidence_ref` enviado por el cliente no prueba
por sí solo titularidad: debe referenciar evidencia verificada por el proceso
aceptado. Cambiar target/destino/evidencia invalida aprobación; preferir caso nuevo.
La ceremonia de operadores debe acreditar personas independientes: dos UUIDs
controlados por la misma persona no son doble control real.

### C2. Saga sin secretos en outbox ni red bajo locks

El store actual `issue_recovery` es una primitiva, NO un endpoint administrativo.
La solución v1 recomendada añade un port técnico de secret delivery con:
`stage`, `publish/reconcile`, `discard`, expiry y claves de idempotencia. El
adaptador real se elige en D2; el fake solo prueba el contrato, no producción.

1. Leer caso approved y generar proof en memoria; solo digest/fingerprint llegarán
   a `request_auth`. Hashes, vault y provider I/O quedan fuera de DB locks.
2. Stage del raw proof en secret store dedicado, cifrado y TTL. No es visible al
   destinatario todavía. Idempotencia por case+issuance generation. Si se pierde la
   respuesta, reconciliar esa misma generación; no generar proof nuevo a ciegas.
   Reservar la generación con CAS sobre el caso antes del I/O. El stage debe ser
   create-if-absent y devolver referencia más digest/fingerprint del secreto
   realmente conservado; en replay se descarta cualquier candidato nuevo en
   memoria. La transacción siguiente usa esa metadata, nunca el digest de un
   candidato que perdió la carrera. Un adaptador sin esta garantía no es apto.
3. Transacción autoritativa: lock gate/actor/caso/authority/identity según B,
   revalidar aprobación y actor, destino y revisiones; insertar recovery intent,
   vincular caso y ticket de entrega; auditar y commit. Invalidar proofs previos
   según la regla vigente de una recuperación pendiente por identidad.
4. Si rollback: staging huérfano se descarta o expira; nunca se publica. El ticket
   durable contiene referencia opaca, no raw/encrypted proof en outbox ordinario.
5. Worker reclama ticket con lease/fencing, comprueba su elegibilidad y realiza
   publish fuera de locks. El vault/adaptador verifica destino aprobado y expiry.
   Un worker no puede cambiar destino ni administrar identidad por argumentos.
6. Finalizar resultado con fence vigente. Un resultado tardío no revive un caso
   revocado. Una entrega que carrera con revocación puede llegar físicamente;
   su proof debe ser inutilizable porque revocar caso revoca intent atómicamente.
7. Timeout ambiguo: estado unknown, reconcile por misma clave si proveedor puede;
   si no puede, intervención. No prometer exactamente una entrega de SMTP. Una
   reemisión explícita crea nueva generación e invalida la anterior antes de ser útil.

Raw proof solo puede salir por el canal seguro al titular. No ponerlo en Location,
querystring de redirects, logs HTTP ni respuesta al admin. Si el producto usa un
frontend de reset, consumir fragment/form de forma segura y aplicar no-referrer,
no analytics y redacción; elegir ese frontend como parte de D2, no inventar URLs.

### C3. Integración con consumo existente

Mantener `POST /auth/native/password:recover` y su401 uniforme. Recuperación no
crea sesión, no activa Principal/binding/membership y no restaura grants. Si se
añade case, su consumo/estado debe quedar ligado atómicamente al intent mediante
la misma transacción. Invalidar por cambios de identidad/proof después de aprobar;
decidir explícitamente si revocar al operador invalida aprobación no ejecutada
(recomendación: sí, revalidar al emitir; no revertir una recuperación ya consumida).

Controlar coste de hashing y abuso: límite de body, rate limits por origen y
presupuesto global; no contador por email que permita enumeración. No loguear body
ni errores de validación con input secreto. Nunca recuperar un token por replay
del Idempotency-Key de administración.

Pruebas C: dos aprobadores/solicitante, falta de titularidad, duplicados,
aprobación expirada, target/revisión cambiado, actor revocado, staging huérfano,
crash antes/después de commit y envío, fence tardío, entrega unknown, revoke contra
publish/consume, un token/dos consumidores, verificación de ausencia de secretos
en tablas/eventos/logs/telemetría. E2E atraviesa la API de caso y delivery de test:
no llamar directamente `service.issue_recovery` como setup del resultado a probar.

## 8. D — Bindings y deshabilitación sin takeover ni alcance global accidental

### D1. Queries y ciclo local de binding

Superficie nueva tenant, owner Tenancy:

| Método y path | operationId propuesto | Capability | Semántica |
| --- | --- | --- | --- |
| GET `/v1/identity-bindings` / `/{binding_id}` | `identity_binding_list` / `identity_binding_get` | `identity.binding.read` | Query scoped con principal filter, status, cursor/limit |
| POST `/{binding_id}:suspend` | `identity_binding_suspend` | `identity.bind` | Active→suspended |
| POST `/{binding_id}:reactivate` | `identity_binding_reactivate` | `identity.bind` | Suspended→active tras revalidar identidad/autoridad |
| POST `/{binding_id}:revoke` | `identity_binding_revoke` | `identity.bind` | Terminal; no borrar history |

Implementado en revisión0046 (D1b): las cuatro filas anteriores existen y están
validadas localmente; la revalidación de continuidad D4 y el orden de locks
root-antes-de-fila están probados por `test_identity_topology_races.py`.

Vistas: binding_id, principal_id, authority_id, subject class, status y revision;
no tokens, verifier ni correlaciones privadas de otros tenants. Exponer subject_id
solo si un contrato de administración justifica su sensibilidad; default omitido.
Foreign y random UUID producen el mismo404, con checks también en reader DB.
Sin capability403; autenticación inválida401; revision/transition/continuidad409.

Commands reciben solo expected_revision y reason; idempotencia B4. No cambiar
principal, authority, subject o tenant mediante PATCH. Revoke nunca permite
reactivar la misma fila ni reusar automáticamente otro ID para retargeting.
Activar un binding no concede grants ni activa una membership suspendida.

Toda operación revalida actor y continuidad B. Retirar un binding tenant cambia
la autoridad efectiva de ese Principal, no revoca globalmente sesiones de una
identidad compartida salvo una política vigente explícita; no confundir ambas
garantías. Verificar que el resolver niega el siguiente uso en ese tenant y que
otro tenant no pierde acceso por accidente.

### D2. Linking self-service con dos pruebas

No habilitar un `POST bindings {principal_id, subject_id}` genérico. Para v1:

1. `POST /v1/me/identity-link-intents`, operationId `identity_link_intent_create`,
   capability propuesta `identity.link_self`; solo HUMAN sin delegación y con
   reautenticación reciente de su identidad actual. Body target_authority_id
   selecciona un autenticador configurado, nunca aporta identidad confiable.
2. Persistir intent de TTL corto ligado a actor, binding actual, target authority,
   revisiones y nonce digest. Respuesta201 con intent ID y expiry, no otro Principal.
3. `POST /v1/me/identity-link-intents/{id}:confirm`,
   `identity_link_intent_confirm`, recibe proof de la segunda identidad mediante
   DTO secreto cerrado, acotado y repr=False. Nunca tokens en query/path/logs.
   Native usa sesión válida; OIDC usa access token del perfil ya aceptado, no ID token.
4. Verificar criptografía/provider I/O fuera de locks. Pasar a la aplicación un
   `AuthenticatedSubject` y un proof stamp interno no fabricable por model args.
   Dentro de transacción revalidar intent, actor, autoridad/config revision y las
   revocaciones locales observables. OIDC sin introspection no garantiza observar
   revocación externa instantánea: declarar esa limitación, no simularla.
5. Crear binding para el MISMO Principal y tenant del actor. Conflicto si subject
   ya está asociado a otro Principal o history impide el vínculo. No merge de
   Principals, Parties, staff ni grants. Consumir intent una sola vez y auditar.
6. Replay exacto bajo actor aún autorizado devuelve recibo sin proof; diferente
   segunda identidad/conflicto409. Proof inválida401 opaca, ID ajeno404.
   El fingerprint se deriva de la identidad verificada y el intent, no del raw
   token ni de un subject_id del body. Si expiró la segunda prueba tras un éxito
   ambiguo, reconciliar mediante la lectura autorizada del binding resultante;
   no relajar la autenticación de confirm ni reusar un nonce para otro sujeto.

No permitir linking administrativo de otro usuario en v1. Recuperación excepcional
de bindings requiere un caso distinto aceptado; no reutilizar la recuperación de
password para conceder acceso de negocio. No hay tools de linking/recovery.

### D3. Disable global de identidad nativa

API privada propuesta: POST
`/v1/platform/native-identities/{native_identity_id}:disable`,
operationId `platform_native_identity_disable`, capability
`platform.identity.disable`, HUMAN global autorizado, expected_revision, reason,
Idempotency-Key. Reader privado list/get previamente requerido para obtener IDs y
revision sin SQL, no enumeración de email pública.

Transacción EXCLUSIVE topology gate: revalidar actor, enumerar impacto, aplicar
continuidad B para todos los tenants y plataforma, native authority/identity locks,
disable terminal + revocar credenciales/sesiones/intents + auditar. Todo o nada.
Conservar bindings/provenance/grants como hechos históricos, no borrarlos ni
reactivarlos. Un eventual nuevo native login handle no hereda esos vínculos.

El caso de migración Native→OIDC debe demostrar: mismo Principal y permisos,
segundo binding explícito válido, native disable, sesión nativa rechazada y acceso
externo permitido. El camino inverso y coexistencia se prueban sin reconstruir
autoridad. Con OIDC deshabilitado por configuración, native-only sigue funcionando.

Pruebas D: mismo email dos identidades, nonce reuse, token de audience equivocada,
ID token, actor/authority revocados entre verify y commit, dos confirmaciones,
dos subjects que intentan tomar mismo binding, tenant foreign/random, A retira B
mientras B retira A, nuevos bindings durante disable global, deshabilitar una
identidad compartida y preservar continuidad/no efectos parciales en todos los
tenants. Un AGENT con grants artificiales no puede invocar commands de identidad.

## 9. E — Políticas existentes, onboarding y diagnóstico accionable

### E1. Policies de controllers existentes

No backfill automático de grants nuevos ni reescritura de v1/v2/v3. Añadir policy
inmutable posterior cuando se acepte el set nuevo. Selección explícita para roots
nuevos; los existentes conservan grants hasta un comando autorizado de upgrade.

Upgrade propuesto: POST `/v1/controller-policy-upgrades`,
`controller_policy_upgrade`, capability tenant-control dedicada y HUMAN autorizado.
Body target_principal_id, source/target_policy_key, expected_authority_revision;
scope tenant del actor y Idempotency-Key. Resolver las policies en el catálogo
inmutable. Solo adiciones explícitas dentro del techo delegable ACTUAL del actor;
no restaurar grants revocados ni deducir aprobación de la versión antigua.
Si nadie tiene techo suficiente, requerir provisioning/recovery de plataforma
explícito; no dejar que el root se autoeleve por ser root.

Antes de habilitar, definir cómo el operador legítimo recibe los nuevos grants
mediante ceremonia de despliegue auditable y narrow. Ni migración SQL masiva ni
auto-update de toda la registry resuelven esa autorización.

### E2. Onboarding identity-aware

Extender el endpoint EXISTENTE `/v1/onboarding/readiness`, operationId
`onboarding_read`, capability `onboarding.read`; no crear un segundo onboarding.

1. Tenancy publica un contrato tipado en `contracts/onboarding_readiness.py` para
   hechos agregados de identity/control: active_controller_with_login_path,
   current_control_policy_ready, staff_administration_available y recovery
   configuration known/ready. Reader least-privilege, tenant scoped y sin PII.
2. Onboarding application compone esos hechos; no importa adapters/SQL internos,
   no provisiona y no decide grants. Extender `OwnerBackedOnboardingReadiness` y
   wiring explícito. Evitar convertir bootstrap en service locator.
3. Añadir secciones `identity`, `tenant_control`, `staff_administration` y
   `recovery` preservando business_party/locations/appointments/queue/communications.
   No exigir queue para una web solo de citas; readiness se evalúa por journey.
4. Bloqueadores estables propuestos: `authentication_path_missing`,
   `active_controller_missing`, `controller_policy_upgrade_required`,
   `staff_management_unavailable`, `recovery_delivery_unconfigured`,
   `recovery_security_operator_missing`. No contar OIDC sin configurar como blocker
   si el camino nativo cumple el journey.
5. Cada blocker: code, owner, resolution_capabilities, opcional operationId
   verificado y `requires_operator`. La acción se filtra por catálogo autorizado;
   mostrar un blocker no concede permiso y no debe revelar identidades globales.
6. Si un reader falla, devolver fallo acotado/estado unknown explícito, nunca ready
   por default. Incluir observed_at y revisiones útiles. Los readers actuales
   usan superficies separadas: no prometer snapshot global atómico sin construir
   ese contrato. Es una proyección advisory que cada comando revalida.
7. Missing schema/authority de despliegue pertenece a readiness de proceso privado,
   no a una lectura tenant que expone detalles operacionales globales.

### E3. Diagnóstico de autoridad efectiva por recurso

No vender `GET /v1/me/authority` ni catálogo como un permiso para cualquier
resource_id. Para cumplir este pendiente del contrato, publicar un Query owner-backed
acotado, por ejemplo POST `/v1/me/authority:inspect` (`authority_inspect_resource`),
capability read específica, sin mutación/idempotency receipt y no-store.

Primera versión: solo operaciones explícitamente soportadas (appointments.book
y supply management), request DTO tipado por operación, actor self, IDs validados
por su dueño. Reusar la policy/query propietaria, no reproducir sus reglas en
Tenancy. Devolver allowed/denied/indeterminate, reason codes y revisiones; no una
garantía de éxito futuro ni disponibilidad de capacidad. Unknown operation422;
foreign y random sin distinguir. No generic payload handler ni SELECT arbitrario.
Definir y aprobar las conexiones sincrónicas antes de agregar imports.

Pruebas E: tenant sin controlador no listo aunque haya supply; native-only listo;
revocar última vía elimina readiness; falta de permiso no revela identidad ni
acción privada; fallos reader no producen ready; dos journeys distintos no se
bloquean por features no usadas; actor AGENT recibe solo acciones de su policy;
upgrade no restaura grants revocados; diagnóstico agree con autorización owner
en la misma revisión y vuelve advisory cuando cambia estado/capacidad.

## 10. Contrato común de ergonomía y errores

Para cada nueva ruta completar el gate docs15/16, no dar por suficiente la tabla:
owner, método/path, operationId único, capability, Query/Command, schema,
concurrencia, idempotencia, autoridad Party/resource, errors y tools/audiencias.

- GET list/detail: sin efectos; filtros closed, cursor opaco bounded; no-store
  para identidad; no secretos/PII por default.
- Semantic commands: POST custom method, IDs de recurso no son autoridad;
  expected_revision en body consistente con las superficies actuales; repetir
  el mismo estado solo como no-op definido, no activación por accidente.
- 401 autenticación/proof inválido opaco; 403 capability/ceiling; 404 ajeno/ausente
  donde aplica privacidad; 409 revisión/estado/continuidad/idempotencia conflict;
  422 entrada inválida; 429 presupuesto; 503 dependencia requerida indisponible.
- `retryable` solo true cuando exista una acción segura definida. Timeout con
  resultado desconocido exige lookup de receipt/caso, no repetir un secreto.
- Catálogo apunta al schema/operationId real; no strings de capability que se
  hagan pasar por comandos. No proyectar nuevas mutaciones de seguridad como tools.
  Queries de onboarding/inspección solo se proyectan si se acepta su audiencia y
  se usa el mismo owner handler, actor y riesgo; no una segunda ejecución.
- Ejemplos completos con valores ficticios, headers necesarios, revisiones y
  resolución de errores; cero SQL para obtener IDs/revisiones en journeys aceptados.

## 11. F — Matriz de pruebas que cierra el producto

Los nombres siguientes son destinos propuestos; no afirmar que ya existen.
Integrar en suites propietarias cuando resulte más cohesivo que crear un archivo.

| ID | Prueba/candidato de archivo | Defecto que debe volverla roja | Boundary/lane |
| --- | --- | --- | --- |
| A-01 | `test_native_enrollment_outcomes` | NULL colapsado a duplicate, gate fuera de transacción | unit + DB + E2E |
| B-01 | `test_identity_control_continuity` | Solo contar grants ignorando autenticabilidad | DB real; current-product |
| B-02 | `test_identity_topology_races` | Writer omitido del gate, discovery race o lock inversion | Conexiones independientes + barreras; DB |
| B-03 | `test_platform_provisioner_lifecycle` | Provisioner se autoeleva o se elimina último control | API privada + DB |
| C-01 | `test_identity_recovery_governance` | Solicitante aprueba su caso, admin tenant resetea global | unit + DB + HTTP |
| C-02 | `test_identity_recovery_delivery` | Envío antes de commit, secreto en outbox, blind retry | Adapter boundary + DB/worker real |
| C-03 | `test_identity_recovery_races` | Dos consumes, replay o revoke resucita proof | DB + HTTP race |
| D-01 | `test_identity_binding_lifecycle` | Admin afecta otro tenant o concede grants al activar | DB role real + HTTP |
| D-02 | `test_identity_link_proofs` | Same-email linking, proof/nonce reuse, actor cambiado | Crypto real + SQL + HTTP |
| D-03 | `test_native_identity_global_disable` | Efecto parcial multi-tenant o control huérfano | DB + private HTTP |
| E-01 | `test_identity_onboarding_readiness` | Ready ficticio, OIDC requerido, fuga global | module + DB + HTTP |
| E-02 | `test_controller_policy_upgrade` | Autoelevar root o restaurar grant revocado | DB + HTTP + upgrade poblado |
| E-03 | `test_resource_authority_inspection` | Diagnóstico y owner policy divergentes | owner/module + DB/HTTP |
| F-01 | Journey fixture-free native | Emisión/recuperación solo existe en helpers | TCP real + DB + worker |
| F-02 | Portabilidad opcional | Cambio de IdP reconstruye Principal/grants | HTTP+crypto reales, fake solo provider externo |
| G-01 | Restore/roll-forward | Readiness verde con schema/roles incorrectos | Entorno aislado production-shaped |

Cada proof documenta riesgo/garantía de current-guarantees, precondición plausible,
operación real, oracle independiente, side effects que no deben ocurrir y lane.
Prohibido: seedear el resultado, rollback antes de comprobar no-mutación, aceptar
una excepción como cualquier rechazo, sleeps como única coordinación, SQLite,
mock de SQL/locks o superuser como evidencia del rol runtime.

Los tests DB nuevos se añaden a la selección explícita de
`scripts/ci/run_current_product.sh`; E2E siguen la colección existente. La prueba
de upgrade poblado debe incorporarse durablemente al runner multi-BD al cerrar
estos bloques; no quedarse solo en `.ci/` scratch. Preservar pruebas de0039/0040.
Revisar sensores semánticos sin split por LOC y sin fabricar human_verdict.

### Journey F-01 obligatorio, sin SQL fixtures para los resultados

1. Arrancar instancia limpia native-only con credenciales de despliegue reales
   de test; ceremonia CLI de bootstrap aceptada, no inserts de Principal/grants.
2. Autenticar controller de plataforma, establecer segundo operador de seguridad
   mediante ceremonia aprobada, provisioner, organización y tenant controller.
3. Crear staff y luego AGENT/INTEGRATION con techos y policy explícitos.
4. Provisionar supply de citas por API, observar onboarding listo para ese journey.
5. Agente descubre operación/schema y agenda con actor propio; caller falsifica
   tenant/party/capability y es rechazado sin reserva ni outbox extra.
6. Revocar acceso local; token válido deja de operar en ese tenant inmediatamente.
7. Recovery case completo: solicitar, aprobar, stage, issue, entregar por adapter
   de test, consumir por HTTP; password viejo/sesiones antiguos fallan; no grants
   restaurados; pérdida de respuesta se reconcilia con nuevo login.
8. Intentar retirar último controlador; falla con código accionable. Establecer
   sustituto válido y repetir según revisión; éxito sin perder provenance.
9. Journey OIDC en prueba separada: dual-proof link, misma autoridad de negocio,
   disable nativo, retirar externo con fallback nativo correctamente establecido.
10. Crash/restart worker y API en puntos de saga; estado y secreto siguen seguros.

## 12. G — Aceptación operacional y publicación

No prometer terminar esta fase solo escribiendo código. D6 debe nombrar entorno,
responsables y umbrales. Compose actual solo tiene PostgreSQL; crear un perfil
de despliegue de referencia aparte, sin convertir credenciales de desarrollo en
defaults de producción ni tocar servicios existentes sin autorización.

Entregables mínimos:

1. Entrypoints reproducibles para API native-only, control plane privado y worker;
   pool/rol separado por superficie. Login de migración no llega al runtime.
2. Startup/readiness verifica schema mínimo, authority/kind/status y privilegios
   imprescindibles; live health no revela infraestructura. Estado de worker y
   delivery se evalúa por probes apropiados, no `SELECT 1` como salud universal.
3. TLS y private ingress verificados desde fuera; negar exposición del control
   plane. CORS limitado por consumidor, sin wildcard con credenciales; headers de
   proxy solo de peers confiables. Tokens explícitos Bearer; si un frontend añade
   cookies, diseñar CSRF/SameSite/secure de ese frontend, no asumirlos resueltos.
4. Body/rate/concurrency/timeouts para login/recovery/link y límites de hashing;
   pruebas de agotamiento y errores sin eco de secretos. Definir presupuestos con
   D6 y medirlos; no fijar cifras de disponibilidad sin evidencia.
5. Secret store/provider configurados, rotación de claves con rollback seguro,
   redacción de logs/traces y permisos mínimos para worker. Simular vault caído,
   provider caído, resultado ambiguo y clave no disponible.
6. Migrations: backup previo, ensayo sobre copia poblada, drain de writers cuando
   cambie lock order, upgrade, catalog/readiness checks, smoke, restaurar tráfico.
   Roll-forward para estados autoritativos; no downgrade que revive credenciales.
7. Backup/restore en entorno aislado y validación de constraints, roles y hechos.
   Riesgo esencial: restaurar una BD antigua puede resucitar sesiones/proofs
   revocados después del backup. Antes de abrir tráfico, procedimiento explícito
   para invalidar credenciales efímeras/epochs y reconciliar staging/delivery.
   Implementar una herramienta narrow de restore-fencing con pruebas; nunca dar
   por seguro el restore porque las tablas se leen.
8. Evidencia del journey providerless real y del canal de entrega seleccionado;
   fake provider no certifica delivery. Ejercicio break-glass con operador humano,
   auditoría y cierre de la elevación temporal; una excepción no se vuelve rol diario.
9. OpenAPI+ejemplos de cliente reproducibles; un developer nuevo debe completar
   setup/agendamiento/revocación sin consultar tablas ni inventar operationIds.
10. Commit exacto, hooks de publicación, GitHub CI/evidence exact-head y PR a
    development según carril. Solo después, promoción release/deployment
    explícitamente autorizados. CI verde no autoriza desplegar por sí mismo.

### Comandos base de validación (adaptar solo tras comprobar entorno)

No reutilizar puertos/credenciales antiguos por memoria. Definir `PGHOST`,
`PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` y `MIGRATION_DATABASE_URL` para la
BD dedicada real. Nunca tests truncantes sobre `request_engine` de la app.
Los valores de la conexión no deben entrar al informe ni a logs de secretos.

```text
git status --short
git branch --show-current
git fetch origin development
git rev-list --left-right --count origin/development...HEAD
uv run alembic heads
uv run alembic upgrade head
uv run pytest <selección del bloque> -q -m postgres --junitxml=<artefacto único>
uv run python scripts/ci/ci_jobs.py python-quality
bash scripts/ci/run_current_product.sh
uv run python scripts/ci/validate_current_proof_execution.py --junit-dir <directorio> --output <reporte>
```

El shell Bash/psql/Python debe ser el previsto por el runner. Probar PostgreSQL18
y Python3.13 en Linux para el perfil production-shaped, no solo Windows con un
PostgreSQL Linux remoto. Dos suites de DB no comparten datos ni roles efímeros
de un clúster durante baseline/multi-DB proof. No borrar roles desconocidos para
hacer pasar instalación; explicar el desvío y usar clúster aislado cuando proceda.

## 13. Definición de terminado y handoff de cada agente

No declarar terminado el branch hasta que:

- [ ] D1–D6 tienen dueño/decisión aceptada y ninguna excepción implícita.
- [ ] A: enrollment distingue unavailable/duplicate dentro de transacción.
- [ ] B: continuidad real y protocolo de todos los writers probados, incluido
  lifecycle de provisioners y último controlador de plataforma.
- [ ] C: recovery completo con aprobación, entrega real, consumo y reconciliación;
  no meras primitivas internas ni reset por email no verificado.
- [ ] D: reads/lifecycle/dual-proof linking y disable global completos sin
  retargeting, efectos cruzados ni autoridad resucitada.
- [ ] E: policies antiguas tienen camino explícito, onboarding identity-aware y
  diagnóstico owner-backed sin prometer permisos futuros.
- [ ] F: journeys fixture-free y matriz adversarial ejecutados en lanes durables;
  no gaps de mapa interpretados como prueba de requisitos todavía sin tests.
- [ ] G: infraestructura, delivery, backup/restore-fencing y break-glass aceptados
  por el operador en el entorno real elegido.
- [ ] Docs/README/OpenAPI/catálogos coinciden; OIDC sigue opcional.
- [ ] Source exacto, revisión semántica/evidencia y CI de merge requeridos completos.

Al terminar cada sesión dejar en `auth-implementation-status.md`:

```text
Bloque/requisito completado y qué cambió para el usuario/sistema
Branch, base, HEAD, dirty state y migraciones antes/después
Decisiones aceptadas y decisiones pendientes con dueño
Archivos/operaciones afectados y contrato actualizado
Entorno real, comandos, conteos, fallos/skips y paths de artefactos
Prueba negativa/mutación que demuestra falsifiabilidad
Qué NO se cambió (DB de app, roles ajenos, deploy, commit/push)
Siguiente bloque exacto y precondiciones; sin promesas de tiempo inventadas
```

**Honestidad final:** hay suficiente diseño y evidencia existente para avanzar
en bloques pequeños, pero no para afirmar que el trabajo restante es solo pulido.
Recovery, linking y continuidad global cambian superficies de takeover y operación.
Si faltan política de titularidad, entrega segura o aceptación de despliegue,
el agente debe entregar código cerrado por defecto y un bloqueo explícito,
no rellenar esos vacíos con un endpoint inseguro ni llamarlo producción lista.
