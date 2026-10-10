# Auditoría de journeys y control de negocio por API — 2026-10-03

## Reporte simple (para humanos)

El sistema permite recorrer varios procesos de negocio, pero la administración
todavía depende demasiado de conservar las respuestas de creación. Un cliente
que cierra y vuelve a abrir necesita poder consultar identificadores,
configuración y versiones actuales; esas lecturas faltan en varias áreas.

La revisión reprodujo dos entradas inválidas que responden como fallos del
servidor. También encontró una contradicción entre catálogo y reservas al
interpretar la cantidad de capacidad requerida. Estos resultados describen el
checkpoint inspeccionado; una corrección posterior debe registrar su evidencia
por separado. No se modificaron datos ni código de producción en esta revisión.

Las 35 pruebas focales ejecutadas pasaron. No equivalen a una evaluación
adversarial completa ni a aceptación de producción. Sigue pendiente demostrar
los contraejemplos de capacidad y reintentos con PostgreSQL real.

## Reporte técnico (detallado)

### Alcance y autoridad

Revisión de los módulos Catalog, Booking, Requests, Queue, Delivery,
Communications y Onboarding. Autoridad: `AGENTS.md`,
`docs/10-module-ownership-map.md`,
`docs/15-api-design-and-usability-standards.md`,
`docs/16-canonical-operation-and-tool-projection-pattern.md` y los READMEs de
los módulos inspeccionados. Las recomendaciones son evolución de superficies
de producto, no una obligación de convertir cada tabla en CRUD.

No se probó PostgreSQL, SMTP ni infraestructura productiva en este subtrabajo.
No se tocó la base local del usuario en 5432. Las referencias de línea indican
el código inspeccionado y pueden desplazarse con cambios posteriores.

### Hallazgos priorizados

#### BJ-001 — P1: entradas inválidas del bootstrap producen 500

Reproducción mediante FastAPI y ASGI real, con el router y handlers globales
actuales y un doble de persistencia que cuenta llamadas:

- `POST /v1/catalog/resource-capabilities`, `capability_key=" "`: HTTP 500,
  cuerpo `Internal Server Error`, cero llamadas de persistencia.
- `POST /v1/catalog/offerings`, requisitos repetidos para el mismo
  `capability_id`: HTTP 500, mismo cuerpo, cero llamadas de persistencia.

Fuentes:

- `src/request_engine/modules/catalog/application/commands/bootstrap_catalog.py:84`
  (`create_resource_capability`, validación de blanco en línea 91).
- El mismo archivo:95 (`create_offering`, duplicado en línea 106).
- El mismo archivo:113 (`_validate_reservation_policy`, validaciones entre campos).
- `src/request_engine/modules/catalog/api/bootstrap_router.py:164`
  (`create_bootstrap_router`, transforma DTO en comando y llama al validador).
- `src/request_engine/entrypoints/http/error_handlers.py:136`
  (`add_global_error_handlers`, sin traducción de `ValueError`).

Corregir mediante validación explícita del DTO o un error de entrada específico
del owner traducido a la respuesta contractual vigente. No capturar globalmente
todo `ValueError`: eso convertiría defectos internos en aparentes errores del
cliente. Extender evidencia a blancos, canales vacíos/repetidos y política de
comunicaciones habilitada sin configuración requerida.

#### BJ-002 — P1: cantidad de recursos y unidades de capacidad se confunden

Fuentes del catálogo:

- `src/request_engine/modules/catalog/adapters/db/offering_catalog_reader.py:128`:
  `count(DISTINCT r.id)` comparado con `req.quantity` en el filtro por ubicación.
- `src/request_engine/modules/catalog/adapters/db/contextual_location_hints.py:53`:
  el mismo criterio en `eligible_location_ids`.

Fuentes de Booking:

- `src/request_engine/modules/booking/adapters/db/reservation_commands.py:550`:
  `revalidate_exact_slot` pasa `requirement.quantity` a la validación del recurso
  concreto elegido; línea 556 agrega unidades por recurso.
- `src/request_engine/modules/booking/domain/availability.py:340`: un recurso
  exclusivo solo admite `required_quantity == 1`.
- El mismo archivo:342: un recurso por unidades comprueba
  `used + required_quantity <= profile.capacity_units`.
- `src/request_engine/modules/booking/README.md`: un requisito obligatorio se
  satisface con un recurso concreto y sus unidades requeridas.

Contraejemplos estructurales, con ubicación y asignaciones activas, misma
capability, horarios válidos, sin ocupación y requisito `quantity=2`:

| Recursos disponibles | Catálogo actual | Booking contractual |
|---|---|---|
| Un recurso `units`, capacidad 2 | Rechaza: `1 < 2` | Puede satisfacer el requisito consumiendo 2 unidades del recurso |
| Dos recursos `exclusive`, capacidad 1 cada uno | Acepta: `2 >= 2` | Ningún recurso individual satisface un requisito de 2 unidades |

Hallazgo confirmado por inspección de semántica y código, **no por ejecución
PostgreSQL**. Corregir la elegibilidad estructural para comprobar capacidad del
recurso candidato. No convertir esta lectura en promesa de disponibilidad:
Booking conserva horarios, ocupación, selección y validación final. También
examinar múltiples requisitos que pueden competir por el mismo recurso.

Prueba pendiente: crear ambos escenarios mediante operaciones del owner en
PostgreSQL 18; comparar búsqueda de catálogo, ubicaciones elegibles, slots y
resultado de compromiso. El oracle debe basarse en la capacidad configurada,
no en reutilizar el helper defectuoso.

#### BJ-003 — P1 funcional: faltan lecturas para reconstruir administración

Fuentes:

- `booking/api/resource_bootstrap_router.py:46`: creación de Resource, sin GET/List.
- `catalog/api/bootstrap_router.py:258`: creación de ResourceCapability.
- `booking/api/operational_assignment_router.py:43`: crear asignación, retirar y
  reemplazar disponibilidad; sin lectura canónica de configuración/revisiones.
- `booking/api/operational_terms_router.py:53`: configurar/superseder términos;
  sin lectura administrativa correspondiente en ese router.
- `communications/api/channel_policy_router.py:50`: solo PUT de política por
  propósito; exige `expected_revision`, sin GET para obtenerla.

Estos paths son relativos a `src/request_engine/modules/`. La búsqueda adicional
del repositorio no encontró routers alternativos de lectura para esas superficies.
Los DTOs de catálogo público no sustituyen configuración administrativa:
`catalog/api/offering_models.py` muestra la versión pública, sin requisitos ni
revisión de política efectiva.

Agregar Queries tipadas de sus respectivos owners para configuración, estado,
identificadores, revisiones e historial pertinente. Prueba de aceptación:
configurar, descartar todas las respuestas retenidas por el cliente, reconstruir
exclusivamente con GET autorizados y ejecutar cambio con revisión actual.
`tests/e2e/booking_world_support.py:311` y siguientes encadena los IDs devueltos
por creación; esa evidencia no demuestra reconstrucción tras reconexión.

#### BJ-004 — P1 funcional: RequestDefinition y bandeja de Requests incompletas

`src/request_engine/modules/requests/api/router.py:82` expone submit por
`request_key`, GET por Request ID y comandos de ciclo de vida. No provisiona
definiciones/versiones ni ofrece discovery del schema o bandeja de demandas.
`requests/adapters/db/request_definition_reader.py:19` solo resuelve definiciones
ya existentes. Un tenant vacío no configura un nuevo tipo de Request por esa API.

Diseñar operaciones semánticas de definición/versionado/activación y lectura del
contrato antes de implementación. Añadir bandeja paginada del owner con autoridad
explícita de operador. Mantener la separación entre requester, recipient,
participación y autoridad. Los comandos result/complete/fail solo se montan con
`include_internal`; eso es una frontera deliberada, no una ruta pública rota.

#### BJ-005 — P2: respuestas administrativas opacas en OpenAPI

Los routers de bootstrap de catálogo, Resource, asignaciones, términos y
políticas de canales usan retorno `object` sin `response_model` específico.
Reproducción de OpenAPI para creación de ResourceCapability:

```json
{"description":"Successful Response","content":{"application/json":{"schema":{"title":"Response Catalog Manage Resource Capabilities"}}}}
```

No describe propiedades ni referencia tipada. Agregar DTO de transporte separado
del estado de aplicación, identificadores y revisiones explícitos, errores
documentados y ejemplos que permitan continuar el journey.

#### BJ-006 — P2: lecturas no recorribles o sin límite de historia

- `catalog/api/router.py:42`: límite 1..200, array sin cursor.
- `catalog/adapters/db/offering_catalog_reader.py:154`: orden y LIMIT, sin
  continuidad. Una colección mayor de 200 no tiene recorrido exhaustivo normal.
- `delivery/api/resource_activity_routes.py:41`: `active_only=false` habilita
  historia sin tamaño/ventana.
- `delivery/adapters/db/resource_activity_reader.py:19`: consulta toda la historia
  del recurso y materializa `.all()`, aunque mantiene tenant y orden estable.

Agregar envelope, tamaño acotado y cursor; historia con ventana pertinente.
Probar empates, segunda página y compatibilidad de filtros/cursor. No se afirma
una vulnerabilidad de aislamiento ni se midió coste de consultas.

#### BJ-007 — P2 candidato: resolución de última definición antes del replay

Fuentes:

- `requests/api/models.py:24`: `definition_version` opcional.
- `requests/api/router.py:94`: resolver definición antes de ejecutar el comando.
- `requests/adapters/db/request_definition_reader.py:39`: exige definición activa
  y, sin versión explícita, selecciona la más reciente.
- `requests/adapters/db/request_commands.py:75`: fingerprint incorpora el UUID
  de la versión resuelta antes de adquirir idempotencia.

Si una definición cambia entre envío y reintento, mismo cuerpo HTTP/key puede
resolver otro UUID y generar conflicto; desactivar definición puede fallar antes
de consultar replay. **Pendiente reproducción PostgreSQL**; no se presenta como
vulnerabilidad. Decidir entre versión obligatoria o resolución original guardada
con identidad de intención y replay previo a resolver de nuevo. Revisar la
garantía de replay y autoridad actual antes de modificar el orden.

### Matriz de capacidades y controles

| Owner / journey | Superficie existente inspeccionada | Control o prueba pendiente |
|---|---|---|
| Catalog: sede/oferta/vocabulario | Creación, sede/horarios/excepciones, búsqueda y detalle público | Versionado/lifecycle administrativo de oferta y vocabulario, lectura de requisitos/política efectiva, cantidades coherentes, paginación |
| Booking: supply y compromiso | Resource create, assignment/availability/exceptions/context terms, slots/book/get/cancel/reschedule | Reconstrucción de supply y revisiones por lectura, verificación de capacidad con catálogo |
| Requests: demanda y procesamiento | Submit/get/cancel; result/complete/fail internos opt-in | Definición/version/schema y bandeja autorizada; replay tras cambio de definición |
| Queue: espera/llamada/waitlist | Cola create/list, join/status/leave/call-next, waitlist, staff live/history y triage | Completar matriz adversarial de autorización, transiciones y replay con evidencia PostgreSQL existente y huecos explícitos |
| Delivery: ejecución | Start/pause/resume/complete/read, resource activity start/end/read | Historia bounded; carreras sesión/ocupación/cola requieren pruebas reales, no lectura estática |
| Communications: intención/entrega | Reminders create/get/cancel, channel policy PUT, workers con reconciliación | Lectura de políticas/revisiones; visibilidad autorizada de tareas/intentos/lineage y aceptación de transporte real |
| Onboarding: readiness | GET advisory con owner/capabilities y algunas referencias operation_id | Supply blockers con sugerencias de operación útiles; conservar unknown de recovery y revalidación en cada owner |

El catálogo de operaciones no sustituye lecturas de hechos de negocio. Las
interfaces y herramientas deben proyectar las mismas operaciones del owner;
Onboarding no debe ejecutar provisioning ni adquirir autoridad por sugerirlo.

### Reproducción auditable BJ-001 / BJ-005

Desde la raíz del repositorio en PowerShell, sin DB ni archivos temporales:

```powershell
@'
import asyncio
from uuid import uuid4
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from request_engine.modules.catalog.api.bootstrap_router import create_bootstrap_router
from request_engine.platform.security.context import ActorContext
from request_engine.entrypoints.http.error_handlers import add_global_error_handlers

class Resolver:
    async def resolve_actor(self, request):
        return ActorContext(organization_id=uuid4(), principal_id=uuid4(),
                            capabilities=frozenset({'catalog.manage'}))

class NeverHandler:
    calls = 0
    async def create_resource_capability(self, command):
        self.calls += 1
        raise AssertionError('must reject before handler')
    async def create_offering(self, command):
        self.calls += 1
        raise AssertionError('must reject before handler')

async def main():
    handler = NeverHandler()
    app = FastAPI()
    add_global_error_handlers(app)
    app.include_router(create_bootstrap_router(handler=handler,
        policy_handler=handler, actor_resolver=Resolver()))
    async with AsyncClient(transport=ASGITransport(app=app,
            raise_app_exceptions=False), base_url='http://test') as client:
        response = await client.post('/v1/catalog/resource-capabilities',
            headers={'Idempotency-Key': 'adversarial-readonly-repro'},
            json={'authority_party_id': str(uuid4()),
                  'capability_key': ' ', 'display_name': 'Name'})
        print('whitespace capability =>', response.status_code, response.text,
              'handler calls', handler.calls)
        cap = str(uuid4())
        response = await client.post('/v1/catalog/offerings',
            headers={'Idempotency-Key': 'adversarial-readonly-repro2'},
            json={'authority_party_id': str(uuid4()), 'offering_key': 'x',
                  'display_name': 'Name', 'duration_minutes': 30,
                  'requirements': [{'capability_id': cap}, {'capability_id': cap}]})
        print('duplicate requirement =>', response.status_code, response.text,
              'handler calls', handler.calls)
    print('resource capability success schema', app.openapi()['paths']
          ['/v1/catalog/resource-capabilities']['post']['responses']['201'])

asyncio.run(main())
'@ | uv run python -
```

Resultado observado en el checkpoint: ambas respuestas 500, contador 0;
schema de éxito opaco mostrado arriba. El doble sirve para aislar validación y
demostrar ausencia de llamada al handler; no prueba persistencia ni autoridad
PostgreSQL. Después de corregir, la regresión debe exigir respuesta de entrada
inválida y ausencia de efectos, no conservar el 500 como expectativa.

### Evidencia ejecutada y límites

```powershell
uv run pytest tests/modules/onboarding/test_readiness_projection.py tests/modules/catalog/test_offering_booking_policy_command.py tests/modules/booking/test_create_resource_weekly_availability.py tests/modules/requests/test_schema_validation.py -q
```

Resultado: **35 passed in 1.63s**. Pruebas locales de módulo; no incluyen DB ni
carreras. No hubo migraciones, commit/push, intervención en servicios ni cambios
de producción en esta revisión. El conjunto completo de endpoints y las
garantías durables necesitan una matriz global y evidencia de sus lanes
canónicos antes de afirmar cobertura adversarial completa.
