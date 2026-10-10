# Auditoría del contrato HTTP, autenticación y descubrimiento — 2026-10-03

## Reporte simple (para humanos)

La revisión encontró dos problemas concretos. La descripción automática de la
API no muestra la autenticación requerida por muchas operaciones. Además, la
entrada con nombre de usuario responde de forma distinta cuando una cuenta
tiene varias llaves de acceso. El primero dificulta construir clientes; el
segundo contradice la protección declarada contra descubrir cuentas existentes.

Las dos consultas de sesión comprobadas rechazaron correctamente una petición
sin sesión. No se demostró que estos problemas permitan saltar permisos. La
recuperación que registra una llave de reemplazo está aceptada por una prueba
vigente; bloquearla sin resolver el reemplazo de llaves perdidas rompería ese
recorrido.

Esta pasada ejecutó 36 pruebas seleccionadas, todas correctas. No modificó código
de producción ni datos. Quedan pendientes las correcciones del contrato y la
comprobación de múltiples llaves por HTTP y PostgreSQL. Esto no certifica todas
las operaciones ni declara el sistema listo para producción.

## Reporte técnico (detallado)

### Alcance y autoridad

Revisión de sólo lectura del código y de los OpenAPI servidos localmente por
runtime `http://localhost:8010` y control `http://localhost:8011`. No se abrió
ninguna conexión directa a PostgreSQL ni se utilizó DB5432 para pruebas. Los
servicios ya estaban iniciados; el inventario caracteriza sus respuestas en ese
momento y no garantiza que cada proceso cargara todos los cambios pendientes del
worktree.

Autoridad normativa consultada: `AGENTS.md`,
`docs/15-api-design-and-usability-standards.md`,
`docs/16-canonical-operation-and-tool-projection-pattern.md` y
`docs/testing/current-guarantees.toml`. Garantías relevantes:
`INV-AUTHORITY-001`, `INV-FAILURE-001`, `INV-NATIVE-WEBAUTHN-LOGIN-001`,
`INV-NATIVE-RECOVERY-POSTURE-001`, `INV-AGENT-POLICY-001`,
`INV-AGENT-RISK-001` y `INV-COPILOT-ADMISSION-001`.

No se modificaron rutas, operationIds, modelos, autorización, sesiones,
recuperación, migraciones, grants ni políticas de proveedores. Este documento
es el único artefacto escrito por esta pasada; no se realizó commit/push.

### H-01 — autenticación ausente en OpenAPI, prioridad P1

Inventario real observado:

| Superficie | Operaciones HTTP | Operaciones con capability | Seguridad ausente en operaciones con capability | 401 ausente en operaciones con capability |
| --- | ---: | ---: | ---: | ---: |
| Runtime 8010 | 204 | 175 | 175 | 169 |
| Control 8011 | 78 | No contado en esta pasada | 6 identificadas | No contado en esta pasada |

Runtime tenía tres operaciones con `SubjectBearer` y 201 operaciones sin
`security`. Todas las 175 operaciones capability tenían owner y no se encontraron
operationIds duplicados dentro de la superficie. Control tenía 40 operaciones
con `NativeSessionBearer` y 38 sin `security`; tampoco se encontraron IDs
duplicados dentro de esa superficie. Los 282 son slots método/path de dos
procesos, no necesariamente 282 operaciones de negocio distintas.

Las seis operaciones capability de control sin seguridad declarada fueron:
`platform_organization_list`, `platform_organization_get`,
`platform_native_identity_provision`, `platform_native_identity_list`,
`platform_native_identity_get` y `platform_native_identity_disable`.

También faltaba seguridad en operaciones auth protegidas: sesión actual,
logout individual/global, reauth, recovery readiness/completion, administración
de direcciones/códigos de recuperación, registro y step-up WebAuthn.
`nativeSessionCreate` declaraba sólo 201/422; los logout sólo 204. La ausencia
de metadata no demuestra ausencia de autenticación en ejecución.

Fuentes:

- `src/request_engine/platform/http/capability_routes.py:29`,
  `add_capability_route`: genera owner/capability/idempotency/revision metadata;
  una autenticación implementada mediante `Request` y resolver no queda
  automáticamente descrita como esquema de seguridad FastAPI.
- `src/request_engine/entrypoints/http/native_auth.py:743`: registro de sesión;
  `:749` y `:756`: logout actual/global; `:785`: introspección; `:1002` a `:1094`:
  registros de ceremonias protegidas y públicas.
- `src/request_engine/entrypoints/http/operation_catalog.py`,
  `create_operation_catalog_router`: discovery autenticado mediante resolver,
  mientras el OpenAPI observado mostraba sólo 200 y ninguna seguridad.
- `src/request_engine/platform/security/native_http.py`, `bearer_token` y
  `NativeSessionHttpSubjectResolver`: autenticación efectiva separada de grants.

Recomendación: declarar esquemas y requisitos reales en la composición del
proceso, incluyendo el contexto tenant cuando corresponde. Documentar 401/403
y errores de owner pertinentes. Conservar operaciones públicas de login y
consumo de proof explícitamente públicas. No imponer `NativeSessionBearer` a
una superficie provider-neutral/OIDC/workload ni inferir autoridad desde
security metadata. Una prueba debe contrastar OpenAPI con el comportamiento
real sin sesión y con permisos insuficientes.

Reproducción del inventario, PowerShell, sólo lectura y sin credenciales:

```powershell
foreach ($port in @(8010, 8011)) {
    $spec = Invoke-RestMethod ('http://localhost:' + $port + '/openapi.json')
    $ops = foreach ($path in $spec.paths.PSObject.Properties) {
        foreach ($method in $path.Value.PSObject.Properties) {
            if ($method.Name -in @('get', 'post', 'put', 'patch', 'delete')) {
                [pscustomobject]@{
                    path = $path.Name
                    method = $method.Name
                    id = $method.Value.operationId
                    capability = $method.Value.'x-request-engine-capability'
                    owner = $method.Value.'x-request-engine-owner'
                    security = ($method.Value.security | ConvertTo-Json -Compress)
                    responses = ($method.Value.responses.PSObject.Properties.Name -join ',')
                }
            }
        }
    }
    [pscustomobject]@{
        port = $port
        operations = @($ops).Count
        capability_ops = @($ops | Where-Object capability).Count
        capability_without_owner = @($ops | Where-Object {
            $_.capability -and -not $_.owner
        }).Count
        capability_without_security = @($ops | Where-Object {
            $_.capability -and $_.security -eq 'null'
        }).Count
        capability_without_401 = @($ops | Where-Object {
            $_.capability -and $_.responses -notmatch '401'
        }).Count
        duplicate_ids = @($ops | Group-Object id | Where-Object Count -gt 1).Count
    } | ConvertTo-Json -Compress
}
```

### H-02 — respuesta 401 sin challenge, prioridad P2

Consultas anónimas reales a control:

```text
GET /auth/native/sessions/current
GET /auth/native/sessions/current/recovery-readiness
```

Ambas devolvieron 401 con `authentication_required`, `retryable=false` y
`resolution=reauthenticate`, pero sin `WWW-Authenticate`.

Fuente: `src/request_engine/entrypoints/http/errors.py:38`,
`authentication_required_handler`, devuelve el envelope sin headers. La falta
de challenge dificulta clientes HTTP estándar; no constituye bypass.
Añadir un challenge coherente con el mecanismo real de autenticación y una
prueba de transporte. No copiar esa decisión indiscriminadamente a autenticación
con otro mecanismo.

Reproducción en PowerShell 7:

```powershell
$response = Invoke-WebRequest http://localhost:8011/auth/native/sessions/current -SkipHttpErrorCheck
$response.StatusCode
$response.Headers['WWW-Authenticate']
$response.Content
```

No enviar cookies ni tokens para esta comprobación.

### H-03 / W-02 — cardinalidad de allow-list, prioridad P1

`NativeWebAuthnLoginService.begin_login`, en
`src/request_engine/platform/security/native_webauthn_login.py:73`, construye
exactamente una credencial decoy para un handle desconocido.
`NativeWebAuthnAuthService.begin_authentication`, en
`src/request_engine/platform/security/native_webauthn_auth.py:256`, devuelve
todas las credenciales activas del handle real. Con dos credenciales las formas
observables difieren.

Reproducción ejecutada con servicios reales, constructor Fido2 instalado y
puertos AsyncMock, sin HTTP, DB ni red externa:

```python
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from request_engine.platform.security.native_webauthn_auth import NativeWebAuthnAuthService
from request_engine.platform.security.native_webauthn_login import NativeWebAuthnLoginService
from request_engine.platform.security.webauthn import WebAuthnPolicy, public_key_to_json


async def main():
    identity = UUID(int=1)
    store = SimpleNamespace(
        read_credentials=AsyncMock(return_value=(
            SimpleNamespace(status='active', credential_id=b'a' * 32),
            SimpleNamespace(status='active', credential_id=b'b' * 32),
        )),
        create_challenge=AsyncMock(return_value=True),
    )
    reader = SimpleNamespace(
        read_active_webauthn_identity=AsyncMock(side_effect=[identity, None])
    )
    ceremony = NativeWebAuthnAuthService(
        policy=WebAuthnPolicy(
            rp_id='localhost', rp_name='Test',
            allowed_origins=frozenset({'http://localhost:8012'}),
        ),
        store=store,
    )
    login = NativeWebAuthnLoginService(
        webauthn=ceremony, identities=reader, decoy_key=b'local-test-only-key'
    )
    known = await login.begin_login(
        identity_authority_id=UUID(int=2), login_handle='fixture@example.test'
    )
    unknown = await login.begin_login(
        identity_authority_id=UUID(int=2), login_handle='absent@example.test'
    )
    print({
        'known_count': len(public_key_to_json(known.public_key)['allowCredentials']),
        'unknown_count': len(public_key_to_json(unknown.public_key)['allowCredentials']),
        'persistent_challenges': store.create_challenge.await_count,
    })


asyncio.run(main())
```

Salida de `uv run python -c $probe`:

```text
{'known_count': 2, 'unknown_count': 1, 'persistent_challenges': 1}
```

La prueba HTTP existente en
`tests/e2e/test_native_webauthn_login_http.py:675` compara una sola credencial
real con una sola decoy; no cubre múltiples llaves. Este contraejemplo verifica
el servicio y la forma serializada, no una enumeración HTTP/PG ni timing.

Decisión pendiente del owner: respuesta uniforme compatible con múltiples
llaves. Truncar a una llave arbitraria puede impedir el login legítimo; padding
sin límite no define un contrato finito. La política elegida debe incluir
límites, compatibilidad de llaves antiguas no discoverable y evidencia de login
con cada llave. El recorrido discoverable no selecciona handle y no presenta
este mismo selector.

### W-03 — reemplazo de factor en recuperación, no defecto demostrado

El documento `docs/testing/admin-session-adversarial-review-2026-10-03.md`
describe el registro de una llave durante recovery. La expectativa positiva de
`test_offline_recovery_restricts_sensitive_authority_until_webauthn_completion`,
en `tests/e2e/test_native_webauthn_login_http.py`, acepta registrar una llave de
reemplazo, demostrarla y completar recovery antes de restaurar autoridad sensible.

No se cambió esa política ni se probó una cadena de ataque. Exigir exclusivamente
un factor original puede impedir recuperar una llave perdida. Un cambio necesita
primero contrato explícito del owner y pruebas positivas/negativas de recuperación
real. Un guard sólo en el panel no protegería la API.

### Aspectos coherentes y deuda observada

| Área | Observación | Límite de la evidencia |
| --- | --- | --- |
| Inputs staff | Invitations y membership mutations principales usan `extra="forbid"` | Inspección del código actual, no fuzz global |
| Staff list | `limit` 1–100, envelope `items/next_cursor`, keyset y orden UUID | No snapshot estable si cambian estado/filtros; UUID no cursor compuesto opaco |
| Validation errors | Envelope incluye location/message/type, omite `input` | Inspección de handler, no todas las excepciones posibles |
| Catalog | Filtra grants, policy allowed/denied y risk; exige owner validation | Unit proofs, no reejecución de HTTP/PG agent policy aquí |
| Tool metadata | ID explícito, owner y audiencias cerradas; metadata no concede grants | Inspección de registro y pruebas de catálogo seleccionadas |

Fuentes adicionales:
`src/request_engine/modules/tenancy/api/staff_membership_reads.py:78`,
`src/request_engine/modules/tenancy/adapters/db/staff_membership_reader.py:351`,
`src/request_engine/modules/tenancy/api/staff_invitations.py:60`,
`src/request_engine/modules/tenancy/api/staff_membership_routes.py:26`,
`src/request_engine/entrypoints/http/errors.py:135` y
`src/request_engine/entrypoints/http/operation_catalog.py`.

### Evidencia y cierre pendiente

Entorno: Windows PowerShell, `uv`, dependencias del lock del repositorio.

```text
uv run pytest tests/unit/test_operation_catalog.py tests/unit/platform/security/test_webauthn.py tests/unit/platform/security/test_privileged_authentication.py -q
36 passed in 4.26s
```

No se ejecutó la lane completa python-quality, PostgreSQL actual, Chrome,
SMTP, despliegue ni CI remoto en esta revisión. Una corrección posterior debe
rerun las pruebas pertinentes sobre el código final. Las observaciones OpenAPI
son un inventario, no prueba de comportamiento adversarial completa de cada
endpoint. No se concede waiver de ninguna garantía ni se afirma producción lista.
