# Auditoría de autoridad API y recorridos administrativos — 2026-10-03

## Reporte simple (para humanos)

La administración de empleados e invitaciones tiene una base coherente, pero la
administración global sigue incompleta. Crear una identidad promete reintentos
seguros sin exigir ni usar la clave necesaria. La administración de responsables
globales tampoco permite consultar los responsables y sus revisiones: perder una
respuesta deja al cliente sin la información para continuar por API.

Se confirmaron filtros ignorados y documentación de autenticación incompleta.
Esta pasada no confirmó una fuga entre organizaciones ni una escalada de permisos.
Las comprobaciones nuevas usaron servicios simulados sin base de datos. No son
pruebas de PostgreSQL, correo productivo o navegador. No se modificó código de
producción ni se accedió a las bases de datos.

## Reporte técnico (detallado)

### Alcance y clasificación de evidencia

La revisión de código, sin modificaciones, abarcó las superficies HTTP de Tenancy
para membresías de empleados, invitaciones, identidades globales, Platform Owners,
aprovisionadores y directorio de organizaciones. Este documento es el único cambio
realizado por el agente revisor. No se leyó ni escribió la base local del usuario
en el puerto 5432.

Fuentes normativas: `docs/15-api-design-and-usability-standards.md`,
`docs/16-canonical-operation-and-tool-projection-pattern.md`, el README de Tenancy,
`docs/architecture/staff-email-invitations.md`,
`docs/architecture/staff-command-replay-authority.md`, y
`docs/architecture/self-organization-discovery.md`.

PROBADO significa una reproducción ASGI del router del módulo responsable o una
operación ausente directamente observable. ESTÁTICO significa una observación de
código pendiente de prueba con base real. Ninguna etiqueta acredita aceptación
del despliegue.

### A1 — PROBADO: crear identidad global incumple la idempotencia declarada (P1)

Fuentes:

- `src/request_engine/modules/tenancy/api/platform_native_identity_management.py:139`,
  `provision_identity`, y registro de ruta en la línea 209.
- `src/request_engine/platform/security/capability_registry_identity_authority.py:154`,
  definición del comando `platform.identity.provision`.
- `src/request_engine/platform/security/capability_types.py:116`, valor predeterminado del comando
  `IdempotencyPolicy.REQUIRED`.
- `src/request_engine/platform/security/native_human_auth.py`,
  `NativeHumanAuthService.enroll_password_identity`.
- `src/request_engine/platform/db/native_human_auth_store.py:70`, `create_identity`.

OpenAPI declara idempotencia obligatoria, pero el endpoint no recibe
Idempotency-Key y llama al alta nativa genérica sin un recibo administrativo
durable. Una reproducción ASGI segura, con un servicio de alta simulado que
registra sus invocaciones, devolvió:

```text
metadata_idempotency required parameters []
missing_key_status 201 owner_calls 1 cache_control None
```

La simulación demuestra que una solicitud sin la clave requerida alcanza el
servicio de alta. No demuestra una escritura real ni una explotación de
autorización. El alta de producción genera UUID nuevos y un login duplicado
produce conflicto; perder una respuesta exitosa impide recuperar el recibo
original mediante un simple reintento.

Cambio recomendado en el módulo responsable:

1. Definir un Command tipado de aprovisionamiento administrativo en Tenancy;
   ubicar allí la orquestación del alta que hoy ejecuta directamente el router.
2. Exigir Idempotency-Key y persistir la huella de intención y el resultado
   original. No incluir contraseña en texto claro en recibos, auditoría o logs.
3. Calcular el hash antes de adquirir bloqueos autoritativos. Después, revalidar
   autoridad actual del actor y crear identidad y recibo en una transacción.
   Diseñar explícitamente orden de bloqueos y privilegios de roles restringidos.
4. La misma clave e intención deben devolver la identidad original; intenciones
   distintas con la misma clave deben rechazarse. Un recibo no restaura autoridad
   retirada.
5. Añadir pruebas PostgreSQL reales de respuesta perdida, reutilización
   conflictiva, ganadores concurrentes, retirada de autoridad y ausencia de
   identidades o efectos de auditoría adicionales. Conservar metadatos veraces;
   reducir la idempotencia declarada para ocultar este hueco no lo resuelve.

Observación relacionada ESTÁTICA: el router comprueba al actor antes del hash y
alta nativos. El almacenamiento técnico no recibe actor y su transacción de
escritura no puede revalidar independientemente la autoridad de este administrador.
Hace falta una prueba real de carrera antes de afirmar que existe un defecto
explotable de autoridad obsoleta.

### A2 — PROBADO: falta el recorrido de consulta de Platform Owners (P1/P2)

`api/platform_owner_management.py:94` exige `expected_revision`; los registros en
las líneas 321–383 permiten crear, registrar, revocar y activar invitaciones, y
suspender, reactivar y revocar responsables. No hay list/get de responsables ni
invitaciones. `platform.owner.read` existe en el registro y políticas.
`tests/unit/admin_console/test_resources.py:700` comprueba expresamente el mensaje
del panel que indica que no existe una operación de enumeración de responsables.

Un cliente que pierde respuestas no puede recuperar invitaciones pendientes,
estado del responsable o la revisión requerida por los comandos de ciclo de vida.
El token debe conservar su entrega única; la falta de consultas no autoriza a
volver a exponerlo.

APIs recomendadas del módulo responsable:

- GET `/v1/platform/owners` y `/{principal_id}` con `platform.owner.read`:
  páginas acotadas y deterministas, estado de principal y binding, revisión de
  autoridad y ciclo de vida actual; sin credenciales ni material de recuperación.
- GET `/v1/platform/owner-invitations` y `/{invitation_id}` con autoridad de lectura
  explícitamente diseñada: estado, revisión, vencimiento y preparación; sin
  token, digest, verificador o referencia del secreto.
- Diseñar por separado la recuperación ante respuesta perdida de creación del
  token. Revocar y crear otra invitación puede ser adecuado; consultar el token
  por GET no lo es.
- Preservar frescura, protección del último controlador y autoridad actual.
  Añadir privilegios precisos de lectura y prueba PostgreSQL antes del panel.

### A3 — PROBADO: se ignoran filtros desconocidos de listado (P2)

- `platform_native_identity_management.py:167` usa
  `Annotated[NativeIdentityListParams, Depends()]`. FastAPI selecciona los
  parámetros declarados antes de construir el modelo; por eso `extra="forbid"`
  no rechaza campos desconocidos de la consulta.
- `platform_provisioner_management.py:158` usa argumentos Query individuales.

Ambos routers aislados aceptaron `?status=suspended&organization_id=<UUID>` con
200 e invocaron el lector simulado. Se ignoraron los campos no soportados.
Incumple doc 15 sección 12, sin demostrar selección de tenant ni elusión de
autorización. Usar DTO cerrados mediante `Query()`, como empleados, directorio de
organizaciones e invitaciones. Las pruebas de rechazo deben comprobar que no se
invocó el lector.

### A4 — PROBADO en router: descripción de autenticación y caché nativas (P2)

OpenAPI del listado de identidades nativas no tenía requisito `security`. El
resolver sí autentica en ejecución: es documentación incompleta, sin evidencia
de acceso anónimo. Las respuestas exitosas GET/POST del router aislado no tenían
Cache-Control; el GET de aprovisionadores devolvió `no-store`.

Inspeccionar el middleware de la aplicación real antes de afirmar un defecto de
caché del despliegue. Proyectar el esquema bearer real en OpenAPI y aplicar
no-store consistentemente a respuestas administrativas de identidad. Los
metadatos descriptivos no reemplazan ni debilitan el resolver.

### A5 — ESTÁTICO, estructura determinista: última página anuncia otra (P3)

- `platform_organization_reads.py:72`
- `platform_provisioner_management.py:171`
- `platform_native_identity_management.py:175`

Devuelven continuación cuando `len(rows) == limit`, sin comprobar una fila
adicional. Una última página completa lleva a una página vacía innecesaria.
Invitaciones y descubrimiento de organizaciones propias ya leen una fila extra.
Adoptar una página tipada del módulo responsable con esa fila interna adicional
y devolver sólo el límite pedido. Ajustar coherentemente límites del lector; no
enviar 101 a una Query cuyo máximo aceptado siga siendo 100.

### Cobertura de recorridos

| Recorrido | Superficie actual | Evaluación |
|---|---|---|
| Invitación por correo, preview/acceptance nativos y permisos | Siete operaciones y plan/apply independiente | Ownership coherente; correo externo y retención requieren aceptación separada |
| Empleado: listado, detalle, perfil, historial y ciclo de vida | Reads y comandos semánticos revisionados | Implementado; pruebas DB inspeccionadas, no ejecutadas aquí |
| Descubrir organizaciones propias | Lectura del sujeto exacto sin selector tenant | Coherente; seleccionar no concede autoridad |
| Identidad global: crear, recuperar recibo y deshabilitar | Create/list/get/disable | Falta idempotencia; decidir correlación de identidad respetando privacidad |
| Aprovisionador: crear, consultar y ciclo de vida | Operaciones principales disponibles | Corregir consultas cerradas y continuación final |
| Responsable: invitar, preparar, activar, consultar y ciclo de vida | Comandos disponibles | Faltan consultas soportadas |
| Organización: crear, listar y consultar | Creación y directorio de sólo lectura | Edición y ciclo de vida requieren diseño de producto, no CRUD automático |

### Comandos y evidencia reproducible

Ejecutado en el entorno Windows existente del repositorio:

```powershell
uv run pytest -q -p no:cacheprovider tests/modules/tenancy/test_staff_membership_admin_router.py tests/modules/tenancy/test_staff_command_input_contract.py tests/modules/tenancy/test_staff_profile_http.py tests/modules/tenancy/test_staff_history_http.py tests/modules/tenancy/test_staff_invitation_list_batch.py tests/modules/tenancy/test_platform_organization_reads.py tests/unit/test_staff_invitation_http.py tests/unit/test_staff_invitation_failure_mapping.py
```

Resultado: **81 pruebas aprobadas en 11.45 segundos**. Este agente no ejecutó
pruebas PostgreSQL.

Reproducción segura de A1: el servicio es simulado y las fábricas de sesiones
nunca abren una conexión:

```powershell
@'
import asyncio
from uuid import uuid4
from types import SimpleNamespace
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from request_engine.modules.tenancy.api.platform_native_identity_management import install_native_identity_management_http
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.context import PrincipalKind
class Resolver:
 async def resolve_platform_actor(self, request):
  return PlatformActorContext(principal_id=uuid4(), principal_kind=PrincipalKind.HUMAN, capabilities=frozenset({'platform.identity.provision'}), authority_revision=1)
class Service:
 calls = 0
 async def enroll_password_identity(self, **kwargs):
  self.calls += 1
  return SimpleNamespace(native_identity_id=uuid4(), login_handle=kwargs['login_handle'])
async def main():
 app = FastAPI(); service = Service()
 install_native_identity_management_http(app, read_session_factory=lambda: None, write_session_factory=lambda: None, actor_resolver=Resolver(), native_auth_service=service, native_authority_id=uuid4())
 operation = app.openapi()['paths']['/v1/platform/native-identities']['post']
 print('metadata_idempotency', operation['x-request-engine-idempotency'], 'parameters', operation.get('parameters', []))
 async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
  response = await client.post('/v1/platform/native-identities', json={'login_handle': 'audit@example.invalid', 'password': 'not-a-real-secret'})
  print('missing_key_status', response.status_code, 'owner_calls', service.calls, 'cache_control', response.headers.get('cache-control'))
asyncio.run(main())
'@ | uv run python -
```

Reproducción segura de A3/A4: las sustituciones existen sólo durante este proceso:

```powershell
@'
import asyncio
from uuid import uuid4
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import request_engine.modules.tenancy.api.platform_native_identity_management as identities
import request_engine.modules.tenancy.api.platform_provisioner_management as provisioners
from request_engine.platform.security.platform_context import PlatformActorContext
from request_engine.platform.security.context import PrincipalKind
class Resolver:
 async def resolve_platform_actor(self, request):
  return PlatformActorContext(principal_id=uuid4(), principal_kind=PrincipalKind.HUMAN, capabilities=frozenset({'platform.identity.read', 'platform.provisioner.read'}), authority_revision=1)
class IdentityReader:
 def __init__(self, *args): pass
 async def list_identities(self, *args): return ()
class ProvisionerReader:
 def __init__(self, *args): pass
 async def list_provisioners(self, *args): return ()
async def main():
 identities.PostgresNativeIdentityReader = IdentityReader
 provisioners.PostgresPlatformProvisionerReader = ProvisionerReader
 app = FastAPI(); resolver = Resolver()
 identities.install_native_identity_management_http(app, read_session_factory=lambda: None, write_session_factory=lambda: None, actor_resolver=resolver, native_auth_service=None, native_authority_id=uuid4())
 provisioners.install_native_platform_provisioner_management_http(app, read_session_factory=lambda: None, write_session_factory=lambda: None, actor_resolver=resolver)
 async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
  for path in ('/v1/platform/native-identities', '/v1/platform/provisioners'):
   response = await client.get(path, params={'status': 'suspended', 'organization_id': str(uuid4())})
   print(path, 'unsupported_filter_status', response.status_code, 'body', response.json(), 'cache_control', response.headers.get('cache-control'))
 print('native_read_security', app.openapi()['paths']['/v1/platform/native-identities']['get'].get('security'))
asyncio.run(main())
'@ | uv run python -
```

Resultado observado: ambas consultas con filtros no soportados devolvieron 200 y
páginas vacías; identidades nativas carecía de no-store y metadatos de seguridad,
y aprovisionadores sí tenía no-store. Se sustituyeron autenticación y base de
datos; estos resultados no acreditan autoridad de extremo a extremo.

### Pruebas existentes inspeccionadas, no ejecutadas

`tests/db/test_staff_email_invitations.py` cubre privacidad del destinatario,
rechazo de sesión, prueba vencida u obsoleta, aceptación sin permisos, rotación de
tokens, retirada del invitador, rechazo de GUC falsificados y carreras de
accept/resend/revoke con transacciones independientes.
`tests/db/test_staff_replay_authority.py` cubre revalidación de autoridad actual
ante recibos completos. Las pruebas HTTP de ciclo de vida y último Platform Owner
están en `tests/e2e/test_native_webauthn_login_http.py`.

Su existencia no constituye nueva evidencia de ejecución. La validación del
agente principal debe usar PostgreSQL 18 con roles restringidos y la vía canónica
actual de CI. Navegador, correo TLS autenticado y bandeja de entrada, y privilegios
del almacén de secretos desplegado quedan fuera de esta auditoría. No se afirma
preparación productiva global ni auditoría completa del sistema.
