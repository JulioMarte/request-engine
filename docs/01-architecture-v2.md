# Request Engine V2 — arquitectura de referencia

> **Estado:** arquitectura objetivo para la reimplementación de Request Engine.
>
> **Documento padre:** `docs/00-product-definition.md`.
>
> Este documento traduce la esencia del producto a decisiones técnicas. Si una decisión técnica entra en conflicto con la definición del producto, **gana la definición del producto**.

---

## 1. Punto de partida

La arquitectura existe para servir esta idea, no para sustituirla:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Request Engine es un **motor headless, multiempresa y API-first de orquestación de solicitudes**.

Su trabajo es:

1. recibir o normalizar una intención;
2. convertirla en un `Request` estructurado;
3. determinar un workflow válido y versionado;
4. ejecutar capabilities deterministas;
5. persistir el estado y las decisiones importantes;
6. esperar callbacks, confirmaciones o intervención humana cuando corresponda;
7. producir un `Fulfillment` verificable;
8. mantener trazabilidad completa.

No es un chatbot, CRM, agenda, PBX, plataforma de WhatsApp ni framework de agentes. Es la capa de negocio que esos sistemas consumen.

---

## 2. Decisiones de arquitectura adoptadas

### Source of truth: PostgreSQL

PostgreSQL será la fuente de verdad transaccional de Request Engine V2.

La decisión se toma porque el dominio es crecientemente relacional y transaccional:

- organizaciones y tenancy;
- contacts;
- request types;
- requests y lifecycle;
- workflow runs;
- resources;
- scheduling;
- bookings;
- idempotency;
- audit;
- domain events;
- reporting y attribution.

PostgreSQL permite expresar mejor las invariantes que Request Engine necesita mediante constraints, índices, transacciones, locking explícito, queries temporales, JSONB cuando aporta valor y capacidades avanzadas de SQL.

No se adopta PostgreSQL porque Convex haya sido un error. Convex fue útil para descubrir el dominio. V2 cambia de tecnología porque **el dominio ya está suficientemente claro como para optimizar alrededor de integridad, relaciones, consultas y control transaccional**.

### Lenguaje del backend: Python

El backend de V2 se implementará en Python.

Python se elige porque Request Engine probablemente combinará durante su evolución:

- API transaccional;
- workflow orchestration;
- background workers;
- integrations;
- AI-assisted classification/extraction;
- agent tooling;
- document/data processing.

Python tiene un ecosistema especialmente fuerte para esos casos y permite mantener el núcleo de negocio y las extensiones AI dentro de un mismo lenguaje cuando eso reduzca complejidad.

**Esta elección no autoriza a mezclar AI con las reglas críticas del dominio.** La IA continúa siendo un consumidor/asistente; las mutaciones autoritativas permanecen tipadas, validadas y deterministas.

### API framework: FastAPI

FastAPI será la capa HTTP inicial.

Motivos principales:

- Pydantic como contratos y validación;
- OpenAPI generado desde la implementación;
- soporte natural para async I/O;
- dependency injection suficiente sin introducir un framework pesado;
- buen fit para SDKs generados y herramientas de agentes.

FastAPI debe ser una **capa de transporte**, no el lugar donde viva el dominio.

### Persistencia: SQLAlchemy + Alembic

SQLAlchemy será la abstracción de persistencia principal y Alembic administrará migraciones.

Se prefiere SQLAlchemy directamente antes que una abstracción más pequeña para evitar quedar limitados cuando aparezcan:

- queries complejas;
- locking;
- PostgreSQL-specific types;
- índices parciales;
- constraints;
- reporting;
- tuning de performance.

Pydantic representa contratos/API. SQLAlchemy representa persistencia. No deben confundirse las responsabilidades.

---

## 3. Principio estructural: modular monolith

V2 comienza como un **modular monolith**, no como microservicios.

```text
request-engine
│
├── API
│
├── Core
│   ├── organizations
│   ├── principals
│   ├── contacts
│   ├── requests
│   ├── workflows
│   ├── fulfillments
│   ├── events
│   ├── idempotency
│   └── audit
│
├── Modules
│   ├── scheduling
│   └── forms
│
├── Infrastructure
│   ├── postgres
│   ├── webhooks
│   ├── integrations
│   └── observability
│
└── Workers
```

Los boundaries son primero boundaries de dominio y código.

Un módulo se convierte en servicio independiente solamente cuando exista una razón concreta:

- scaling diferente;
- failure isolation;
- ownership independiente;
- deployment cadence diferente;
- requirements de seguridad o infraestructura distintos.

“Podría ser un microservicio” no es una razón suficiente.

---

## 4. Estructura propuesta del repositorio

```text
request-engine/
│
├── src/
│   └── request_engine/
│       │
│       ├── api/
│       │   ├── routes/
│       │   ├── dependencies/
│       │   ├── middleware/
│       │   └── errors.py
│       │
│       ├── domain/
│       │   ├── organizations/
│       │   ├── principals/
│       │   ├── contacts/
│       │   ├── requests/
│       │   ├── workflows/
│       │   ├── fulfillments/
│       │   ├── scheduling/
│       │   └── forms/
│       │
│       ├── application/
│       │   ├── commands/
│       │   ├── queries/
│       │   └── services/
│       │
│       ├── infrastructure/
│       │   ├── postgres/
│       │   ├── webhooks/
│       │   ├── integrations/
│       │   └── observability/
│       │
│       └── workers/
│
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
│
├── docs/
├── pyproject.toml
└── README.md
```

Esto es una guía, no una religión. No crear capas vacías solamente para satisfacer el diagrama.

---

## 5. Regla de dependencia

La dirección deseada es:

```text
API / Worker / Integrations
            ↓
      Application layer
            ↓
        Domain rules
            ↓
  Infrastructure adapters
```

Más precisamente:

- routes HTTP traducen requests externos a commands/queries;
- application services coordinan casos de uso;
- domain code expresa invariantes y state transitions;
- repositories/adapters resuelven persistencia o sistemas externos;
- workers consumen outbox/jobs y llaman application services cuando corresponde.

Evitar dos extremos:

1. **fat routes** con toda la lógica dentro de `@app.post(...)`;
2. una Clean Architecture ceremonial con cinco interfaces para insertar una fila.

El objetivo es separación útil, no cantidad de abstracciones.

---

## 6. Contratos: Pydantic → OpenAPI → SDK

V1 mantenía OpenAPI manualmente separado de implementación. V2 no debe repetir ese patrón.

La dirección será:

```text
Pydantic request/response schemas
              ↓
           FastAPI
              ↓
            OpenAPI
              ↓
      generated client SDKs
```

El frontend TypeScript, widgets y agentes Node pueden consumir un SDK generado a partir del contrato OpenAPI.

La API es un verdadero boundary. No es un problema que Python y TypeScript no compartan tipos por imports internos.

De hecho, esa separación obliga a mantener contratos explícitos y reduce acoplamiento accidental entre backend y UI.

---

## 7. PostgreSQL: modelo relacional primero, JSONB con disciplina

No convertir PostgreSQL en un document store accidental.

Campos que participan en identidad, relaciones, lifecycle, búsqueda, constraints o reporting deben ser columnas tipadas.

Ejemplo conceptual de `requests`:

```text
id
public_id
organization_id
contact_id
request_type_id
status
workflow_key
workflow_version
current_step
input_data JSONB
output_data JSONB
metadata JSONB
created_at
updated_at
completed_at
```

JSONB es apropiado para datos dinámicos cuyo schema depende del `RequestType`, metadata o snapshots.

JSONB no debe sustituir foreign keys, estados fundamentales ni campos usados regularmente para filtros y joins.

---

## 8. Multi-tenancy

Toda operación tenant-owned debe ejecutarse dentro de un contexto de organización resuelto desde la credencial/principal.

```text
credential
    ↓
authenticate
    ↓
resolve principal + organization + scopes
    ↓
application command/query
```

Reglas:

- `organization_id` en entidades tenant-owned relevantes;
- foreign keys y unique constraints deben incluir tenant scope cuando corresponda;
- no aceptar ciegamente un tenant enviado por browser;
- public/browser credentials y secret/server credentials son clases distintas;
- tests de cross-tenant leakage son obligatorios.

PostgreSQL Row Level Security puede evaluarse como defensa adicional, pero **no debe introducirse automáticamente como sustituto de authorization correcto en application code**. Si se adopta, debe documentarse en un ADR con su threat model y estrategia de conexión/pooling.

---

## 9. IDs

Conservar la distinción de V1 entre identidad interna y pública.

Conceptualmente:

```text
internal primary key → database concern
public_id            → API/domain reference
external_id          → integration mapping
```

Ejemplos públicos:

```text
org_...
cnt_...
req_...
bkg_...
ful_...
evt_...
```

No usar IDs de Chatwoot, Twilio, LiveKit, Evolution o cualquier provider como identidad primaria del dominio.

---

## 10. Commands y Queries

Separar conceptualmente reads de state-changing operations sin implementar CQRS distribuido.

### Commands

Ejemplos:

```text
CreateRequest
ProvideRequestData
AdvanceRequest
CreateBooking
CancelBooking
CompleteRequest
```

Commands:

- validan authorization;
- ejecutan invariantes;
- participan en una transacción;
- pueden producir domain events;
- son idempotentes cuando el riesgo de retry lo exige.

### Queries

Ejemplos:

```text
GetRequest
ListOpenRequests
SearchAvailability
GetBooking
```

Queries no deben producir side effects de negocio.

En particular, **consultar disponibilidad no debe crear persistent offers por defecto**.

---

## 11. Transacciones

Las transacciones deben ser cortas y contener solamente trabajo autoritativo interno.

Correcto:

```text
BEGIN
  validate current state
  lock/revalidate required rows
  mutate domain state
  insert domain event/outbox record
COMMIT
```

Incorrecto:

```text
BEGIN
  mutate
  call WhatsApp
  call LiveKit
  call n8n
  wait for remote provider
COMMIT
```

Ningún sistema remoto debe mantener abierta una transacción de negocio.

---

## 12. Outbox: PostgreSQL primero

V2 conservará el transactional outbox de V1.

Inicialmente no necesitamos Kafka, RabbitMQ ni una plataforma de eventos distribuida.

El mismo commit de negocio puede persistir:

```text
domain state
+
outbox event
```

Un worker procesa eventos disponibles usando locking apropiado, conceptualmente:

```sql
SELECT ...
FROM outbox_events
WHERE status = 'pending'
  AND available_at <= now()
ORDER BY available_at
FOR UPDATE SKIP LOCKED
LIMIT ...;
```

Esto permite múltiples workers sin procesar la misma fila simultáneamente.

El worker debe soportar:

- leases o ownership explícito cuando sea necesario;
- retries con backoff;
- dead-letter/failure state;
- idempotent delivery;
- observabilidad;
- event versioning.

Una queue externa se incorpora cuando Postgres deje de ser suficiente por requisitos medidos, no por anticipación.

---

## 13. Domain events y audit no son lo mismo

### Domain events

Expresan algo que ocurrió en el negocio:

```text
request.created
request.classified
request.ready
booking.created
booking.cancelled
request.fulfilled
```

Pueden alimentar:

- webhooks;
- notifications;
- analytics;
- projections;
- integrations.

### Audit

Responde quién hizo qué y por qué:

```text
principal
operation
target
before/after or change summary
reason
correlation_id
occurred_at
```

### Logs

Sirven para diagnóstico técnico.

No confundir las tres cosas.

---

## 14. Correlation y causality

Desde el primer día, cada operación importante debe ser rastreable.

Valores conceptuales:

```text
request_id
correlation_id
causation_id
principal_id
trace_id
```

Objetivo:

```text
conversation/input
      ↓
request
      ↓
workflow decision
      ↓
tool/capability call
      ↓
transaction
      ↓
domain event
      ↓
outbox
      ↓
external callback
```

Debe ser posible reconstruir esa cadena sin depender de memoria humana.

Esto es especialmente importante cuando agentes de IA son clientes del API.

---

## 15. Workflow engine: pequeño y explícito

No construir Temporal, BPMN o un workflow designer universal como parte del MVP.

V2 comienza con workflows versionados representados como state machines/código tipado.

Un request puede persistir como mínimo:

```text
workflow_key
workflow_version
workflow_state
current_step
status
next_action_at
```

Un workflow debe poder producir resultados como:

```text
need_input
execute_capability
wait_confirmation
wait_external
wait_human
complete
fail_recoverable
fail_terminal
```

Cuando aparezcan requisitos reales de durable execution mucho más complejos —timers extensos, sagas multi-servicio, fan-out, workflows de días/semanas— se evaluará una plataforma especializada mediante ADR.

No construir una versión casera de Temporal por accidente.

---

## 16. Scheduling como módulo, no identidad del producto

Scheduling será el primer capability module importante, pero Request Engine no vuelve a ser “el booking system”.

Boundary conceptual:

```text
Request workflow
      ↓
scheduling.search_availability
      ↓
scheduling.create_offer       [cuando corresponda]
      ↓
scheduling.create_booking
      ↓
Fulfillment references booking
```

Buenas decisiones de V1 que se mantienen:

- UTC interno + IANA timezone;
- buffers;
- resources;
- capacity;
- revalidación antes del commit;
- idempotency;
- snapshots;
- side effects post-commit.

### PostgreSQL y conflictos temporales

V2 debe aprovechar capacidades nativas de PostgreSQL cuando simplifiquen invariantes:

- `timestamptz` para instantes;
- índices compuestos y parciales;
- range types cuando el modelo lo justifique;
- exclusion constraints cuando puedan impedir overlaps inválidos a nivel de DB;
- row locks/advisory locks solamente con una razón documentada.

No duplicar en Python una garantía que PostgreSQL puede imponer de forma más segura y clara.

---

## 17. Async Python: dónde sí y dónde no

FastAPI y los adapters externos pueden usar async porque el sistema realiza mucho I/O.

Usar async para:

- HTTP clients;
- DB I/O si el stack elegido lo soporta de manera consistente;
- external integrations;
- concurrent independent reads cuando sean seguras.

No usar async como argumento para paralelizar mutaciones que deben mantener orden o consistencia.

La prioridad es una transacción correcta, no maximizar concurrencia artificialmente.

---

## 18. AI boundary

Python facilita integrar AI, pero eso aumenta el riesgo de contaminar el core.

Regla:

```text
AI interprets / proposes
        ↓
structured candidate
        ↓
Request Engine validates
        ↓
deterministic workflow/policy
        ↓
typed capability
        ↓
authoritative transaction
```

El modelo puede sugerir:

```text
intent = "emergency_service"
fields = {...}
```

El modelo no puede decidir por sí solo:

```text
UPDATE bookings SET ...
```

Los agentes reciben APIs/tools con schemas explícitos y scopes mínimos.

---

## 19. Integraciones son adapters

Chatwoot, WhatsApp, LiveKit, Twilio, n8n y similares se conectan alrededor de Request Engine.

Ejemplo:

```text
Chatwoot event
     ↓
Chatwoot adapter
     ↓
Request Engine API
     ↓
Request/workflow
```

No:

```text
Request Engine core
     ↓
provision and own Chatwoot internals
```

n8n puede orquestar integraciones temporales o low-code, pero **no es el workflow engine autoritativo de Request Engine**.

LiveKit puede exponer voice agents, pero **no es el owner de request state**.

Chatwoot puede guardar conversaciones, pero **no es el owner del trabajo estructurado**.

---

## 20. Forms / public intake

Forms será un módulo pequeño inicialmente.

Primitivas:

```text
FormDefinition
FormSubmission
```

El submit puede desencadenar:

```text
upsert contact
      ↓
create/provide data to request
      ↓
emit event
      ↓
resume workflow
```

No construir en V2 inicial:

- drag-and-drop builder avanzado;
- centenares de field types;
- theme engine;
- conditional logic universal;
- competitor completo de Typeform/Jotform.

---

## 21. Security baseline

Desde el principio:

- credentials nunca en frontend salvo credenciales deliberadamente públicas y restringidas;
- API keys secretas almacenadas hashed, no reversibles;
- scopes explícitos;
- expiración/revocación;
- rate limits para superficies públicas;
- webhook signatures + anti-replay cuando corresponda;
- encrypted secrets mediante un secrets manager/environment seguro;
- PII sensible cifrada adicionalmente cuando threat model/regulación lo justifique;
- audit para operaciones privilegiadas;
- cross-tenant tests.

No diseñar seguridad exclusivamente alrededor de “URLs difíciles de adivinar”.

---

## 22. Observabilidad

Request Engine debe nacer observable.

Mínimo:

- structured logs;
- correlation IDs;
- metrics básicas;
- traces OpenTelemetry cuando aporten diagnóstico real;
- health/readiness endpoints;
- DB pool metrics;
- worker queue/outbox lag;
- error classification;
- sanitized request context.

Nunca loggear secrets o PII completa para “hacer debugging más fácil”.

---

## 23. Testing strategy

V1 demostró demasiada superficie con pocos tests. V2 debe invertir la proporción.

Prioridades:

### Unit tests

- state transitions;
- workflow decisions;
- policies;
- temporal calculations;
- validation.

### Integration tests con PostgreSQL real

- transactions;
- constraints;
- idempotency;
- concurrency;
- locking;
- cross-tenant isolation;
- booking conflict prevention;
- outbox claiming/retry.

SQLite no debe ser sustituto del comportamiento PostgreSQL para tests de invariantes PostgreSQL-specific.

### Contract tests

- API schemas;
- generated OpenAPI;
- webhook signatures;
- backwards compatibility relevante.

### End-to-end vertical slice

No se considera V2 viable hasta demostrar el vertical slice definido en `00-product-definition.md` con dos organizaciones distintas.

---

## 24. Performance philosophy

Primero integridad y observabilidad; después optimización medida.

Evitar desde el comienzo patrones que sabemos que escalan mal:

- cargar historial completo para detectar un overlap;
- N+1 por cada candidate slot;
- scans sin límites;
- JSONB para todo;
- synchronous remote calls dentro de transactions;
- generar registros persistentes por cada interacción de UI si no tienen valor de negocio.

Usar PostgreSQL para hacer set-based queries y constraints cuando sea el lugar correcto.

Introducir caches solamente después de identificar reads que realmente lo requieren.

---

## 25. Deployment inicial

La topología mínima deseada es pequeña:

```text
                  ┌─────────────┐
Clients ─────────►│ FastAPI API │
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │ PostgreSQL  │
                  └──────┬──────┘
                         │
                         ▼
                  ┌─────────────┐
                  │   Worker    │
                  └──────┬──────┘
                         │
                 external systems
```

API y Worker pueden usar la misma codebase y dominio, con procesos/deployables separados.

No Redis obligatorio.
No RabbitMQ obligatorio.
No Kafka obligatorio.
No workflow platform obligatoria.

Se agregan solamente cuando exista un requisito que PostgreSQL + worker no resuelva bien.

---

## 26. Lo que Python NO arregla

Esta decisión debe quedar explícita para evitar repetir V1 en otro lenguaje.

Python no arregla:

- un dominio mal definido;
- boundaries pobres;
- coupling a vendors;
- ausencia de tests;
- endpoints con demasiadas responsabilidades;
- schemas genéricos sin disciplina;
- premature feature expansion;
- falta de observabilidad.

Un FastAPI spaghetti monolith sería peor que un TypeScript monolith bien diseñado.

El éxito de V2 depende más de preservar los boundaries que de elegir Python.

---

## 27. Definition of Done para la foundation

Antes de construir features verticales adicionales, la foundation debe demostrar:

```text
[ ] Python/FastAPI service bootstrapped
[ ] PostgreSQL migrations reproducibles
[ ] organizations/principals tenancy
[ ] contacts
[ ] request_types
[ ] requests + lifecycle
[ ] versioned workflow interface
[ ] scheduling minimal capability
[ ] booking con concurrency protection
[ ] fulfillment linked to request
[ ] domain events
[ ] transactional outbox
[ ] worker retry/idempotency
[ ] audit trail
[ ] secret + public credential model
[ ] OpenAPI generated from real schemas
[ ] TypeScript SDK generation proof
[ ] structured logs/correlation IDs
[ ] integration tests using PostgreSQL
[ ] QuisqueyaTech vertical slice
[ ] Demo Plumbing vertical slice
```

Hasta entonces, features como insurance, advanced waitlists, omnichannel provisioning o AI runtime no deben competir por prioridad.

---

## 28. Regla arquitectónica final

Ante una nueva feature, preguntar en este orden:

```text
Does it help represent a request?
          │
          ├─ no → likely outside Request Engine
          │
          ▼ yes
Does it help determine/execute its workflow?
          │
          ├─ no → likely adapter/vertical concern
          │
          ▼ yes
Does it need authoritative persisted state?
          │
          ├─ no → keep it at the edge when possible
          │
          ▼ yes
Core, module, or integration?
```

La arquitectura debe permanecer subordinada a la esencia:

```text
Something requests something
           ↓
Request Engine determines
           ↓
what workflow should happen
```

Todo lo demás es implementación.
