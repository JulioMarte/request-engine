# Request Engine — Database Access Contract

> **Estado:** normativo para la frontera Python ↔ PostgreSQL. Este documento complementa `00-product-definition.md`, `01-architecture-v2.md` y `02-pre-sql-domain-contract.md`; no redefine el dominio.
>
> **Decisión:** PostgreSQL es una base de datos inteligente y autoritativa, no un segundo application backend. Python/FastAPI conserva el ownership de commands, policy orchestration y transacciones de negocio. PostgreSQL expone una superficie deliberada de lectura y primitives atómicas estrechas.

---

## 1. Contexto y problema

El modelo V2.x ya depende de PostgreSQL para:

- tenant-aware referential integrity;
- stable serialization roots y row locks;
- capacity conflict protection;
- financial/outcome invariants;
- idempotency persistence;
- append-oriented facts;
- audit, domain events y transactional outbox.

Sin una frontera explícita, una implementación Python podría degradar el diseño de dos formas opuestas:

```text
A) DB como almacenamiento tonto
FastAPI → ORM CRUD → tablas

B) DB como segundo backend
FastAPI → stored procedures que implementan workflows completos
```

Ambos extremos se rechazan.

La arquitectura objetivo es:

```text
HTTP / Agent / Webhook / Worker
              │
              ▼
      FastAPI / adapters
              │
              ▼
       Application layer
  authorization / policy / idempotency
              │
              ▼
       SQLAlchemy Unit of Work
        one DB transaction
              │
      ┌───────┴────────┐
      │                │
 COMMAND SIDE       QUERY SIDE
      │                │
repositories +      request_read.*
request_cmd.*       versioned views
      │                │
      └───────┬────────┘
              ▼
       request_engine.*
 authoritative relational model
 constraints / locks / revisions
              │
              ▼
 domain_event + outbox
```

---

## 2. Decisión de ownership

### Python/Application layer es dueño de

- command semantics (`ConfirmReservation`, `AllocatePayment`, `RecordFulfillment`, etc.);
- Principal/Representation authorization;
- business policy evaluation y policy version selection;
- planificación del lock set completo;
- canonical lock ordering entre múltiples roots;
- external calls, provider integrations y external snapshots;
- retries de serialization/deadlock cuando correspondan;
- domain orchestration y recovery decisions;
- API/DTO contracts.

### PostgreSQL es dueño de

- structural truth mediante PK/FK/UNIQUE/CHECK/EXCLUDE;
- tenant equality en authoritative relationships;
- stable rows utilizadas para serialization;
- row locks y atomicity;
- local monotonicity / append-only history;
- narrow aggregate safety backstops;
- durable idempotency records;
- current authoritative rows/facts;
- transactional audit/event/outbox persistence.

### Prohibido

```text
table == public API resource
Pydantic model == SQLAlchemy model == table
PATCH arbitrary authoritative fields
writable business views
INSTEAD OF triggers that interpret domain commands
stored procedure monoliths that duplicate the Python application layer
network calls from PostgreSQL
COMMIT/ROLLBACK hidden inside business routines called by Python commands
materialized-view state used as mutation authority
```

---

## 3. PostgreSQL schemas y su responsabilidad

### `request_engine`

Modelo autoritativo interno.

Contiene:

- tables;
- constraints;
- internal triggers;
- internal helper functions required by integrity enforcement.

No constituye una API pública.

### `request_read`

Read contract estable y versionado para Query Services.

Convenciones:

```text
<concept>_v1
<concept>_v2
...
```

Rules:

1. views son conceptualmente read-only;
2. no `INSTEAD OF` write triggers;
3. no view puede ser fuente autoritativa para una mutation sin revalidation bajo lock/revision;
4. cambiar columnas, significado o tipos de forma incompatible crea una nueva versión;
5. la versión anterior permanece durante una ventana de migración de consumers;
6. views pueden componer joins/projections, pero no esconder network/policy decisions;
7. `security_invoker=true` es el default para permanecer compatible con un futuro modelo RLS basado en el caller;
8. una `security_invoker` view **no es una privilege boundary**: el caller necesita permisos sobre la view y las relaciones base requeridas. Su propósito primario aquí es estabilidad semántica/query composition, no privilege elevation.

Si en el futuro se requiere que una read view oculte completamente las tablas base a un role, eso será una decisión de security architecture separada y deberá diseñarse junto con RLS/view ownership; no se obtendrá accidentalmente cambiando flags.

### `request_cmd`

Primitives PostgreSQL explícitas y estrechas.

Una routine puede existir aquí sólo si encapsula una operación data-centric que es más segura/atómica junto a los datos.

Buenos ejemplos:

```text
lock_capacity_authorities(...)
advance_planning_revision(...)
acquire_idempotency(...)
complete_idempotency(...)
claim_outbox_batch(...)
mark_outbox_delivered(...)
release_outbox_claim(...)
```

Malos ejemplos:

```text
process_booking_and_payment(...)
complete_customer_workflow(...)
reschedule_and_notify_customer(...)
```

Regla:

> `request_cmd` encapsula primitives de consistencia; Python conserva workflows y commands de dominio.

### `request_admin`

Views diagnósticas/operacionales para DBA, support y reconciliation tooling.

No es API de producto y no concede authority.

---

## 4. Functions vs procedures

Default V2.x:

```text
FUNCTION > PROCEDURE
```

cuando necesitamos una primitive DB.

Razón:

- Python debe ser dueño de `BEGIN/COMMIT/ROLLBACK`;
- la routine debe participar en la misma transacción SQLAlchemy del command;
- funciones pueden devolver rows/values útiles a repositories;
- evitamos control transaccional interno que fragmente la atomicidad del command.

`CREATE PROCEDURE` sólo se introduce si existe un caso administrativo/maintenance independiente cuya necesidad esté demostrada y que no represente un domain workflow duplicado.

### Reglas para `request_cmd` functions

- schema-qualified objects;
- `SECURITY INVOKER` por defecto;
- `SECURITY INVOKER` significa que la routine **no eleva privileges**: el caller debe tener los permisos necesarios sobre los objetos subyacentes además de `EXECUTE`;
- `VOLATILE` cuando modifica DB o adquiere locks;
- `STABLE` sólo para lecturas que satisfagan realmente esa semántica;
- `IMMUTABLE` sólo para funciones puras sin DB/time/session dependence;
- explicit `search_path` seguro;
- `EXECUTE` revocado de `PUBLIC` en la misma migration;
- no dynamic SQL salvo necesidad demostrada;
- no generic `(entity_type, entity_id)` authority;
- no external I/O;
- no hidden cross-root lock plan distinto al contrato;
- routines pequeñas, testeables y con una sola responsabilidad.

`SECURITY DEFINER` no es default. Si algún caso futuro lo requiere para crear una privilege boundary real, debe tener threat model, `search_path` cerrado, grants mínimos, owner no-runtime y tests específicos contra privilege escalation.

---

## 5. SQLAlchemy / Unit of Work contract

Cada command autoritativo usa una única SQLAlchemy `Session` y una única DB transaction salvo que el command protocol documente expresamente otra cosa.

Preferencia para la implementación:

```python
async with session.begin():
    ...
```

Para commands críticos se recomienda `autobegin=False` o una disciplina equivalente para hacer visible el inicio de transaction y evitar DB work accidental fuera del Unit of Work.

### ORM vs SQLAlchemy Core

ORM es apropiado para:

- simple row loading;
- inserts de aggregates/facts;
- ordinary typed relationships;
- non-contentious persistence.

SQLAlchemy Core / explicit SQL es preferido para:

- `SELECT ... FOR UPDATE`;
- canonical multi-row locks;
- `SKIP LOCKED`;
- PostgreSQL range operators;
- aggregate concurrency checks;
- bulk worker operations;
- `request_cmd` functions.

Correctness no debe depender de lazy loading o del orden accidental en que el ORM recorra relationships.

---

## 6. Transaction boundary

No mantener una authoritative DB transaction abierta durante I/O externo.

Correcto:

```text
external read / lease / feasibility call
        ↓
snapshot + provider reference + revision R
        ↓
BEGIN
lock authoritative roots
revalidate R/current state
write authoritative state
append audit/event/outbox
COMMIT
        ↓
async side effects / compensation workers
```

Incorrecto:

```text
BEGIN
lock rows
HTTP call / LLM / provider / routing
wait
write
COMMIT
```

---

## 7. Command repository contract

Repositories no son generic CRUD stores.

Preferir interfaces semánticas:

```text
lock_request(...)
lock_outcome_scope(...)
lock_capacity_authorities(...)
insert_capacity_claim(...)
release_capacity_claim(...)
lock_payment_transaction(...)
lock_payment_requirements(...)
append_financial_observation(...)
append_payment_allocation(...)
```

Evitar una abstraction universal:

```text
save(entity)
update(entity, arbitrary_fields)
```

cuando la operación representa un commitment/lifecycle transition.

Un repository puede escribir directamente `request_engine` cuando el command protocol requiere múltiples writes en una sola UoW. No es obligatorio canalizar todo write por stored functions.

---

## 8. Query contract

Query Services deben preferir `request_read.*` para read models reutilizados por API, workers o admin UI.

La API pública no es una exposición automática de esas views. El flujo sigue siendo:

```text
request_read view
     ↓
Python QueryService
     ↓
Pydantic response DTO
     ↓
FastAPI/OpenAPI
```

Los internal bigint IDs pueden existir en views para repositories/query services, pero no se exponen por defecto al cliente. Public IDs siguen siendo identifiers de API, nunca authority tokens.

`request_read` estandariza el contrato de consultas, pero con `security_invoker=true` no pretende impedir técnicamente un `SELECT` directo sobre las tablas para un role que ya tiene ese permiso. La disciplina de repositories/query services y el futuro privilege/RLS model cumplen responsabilidades distintas.

---

## 9. Materialized views

No crear materialized views por defecto.

Candidatos futuros sólo después de profiling:

- availability search projections;
- historical utilization;
- operations dashboards;
- analytics/reporting.

No pueden autorizar:

- Reservation confirmation;
- CapacityHold acquisition;
- Payment allocation;
- Request completion;
- refund budget;
- authority checks.

Toda mutation revalida authoritative rows/revisions bajo la transaction protocol correspondiente.

---

## 10. Role / privilege model

Roles conceptuales de deployment:

```text
request_migrator
request_app
request_worker
request_readonly
request_admin_role
```

No se crean dentro de la portable schema migration porque role provisioning es cluster/deployment-specific y requiere privilegios distintos a DDL de aplicación.

Principios:

- migration owner controla DDL;
- `PUBLIC` no recibe `CREATE`/`USAGE` implícito en los schemas de interface;
- `PUBLIC` no recibe `EXECUTE` en `request_cmd`;
- `SECURITY INVOKER` views/functions no elevan privileges;
- app/worker/read roles reciben sólo los privileges de objetos base + interfaces que realmente necesitan;
- command repositories pueden requerir DML directo sobre un conjunto explícito de `request_engine` tables porque no todo write se canaliza por functions;
- query roles que usan `security_invoker` views requieren `SELECT` en las relaciones base referenciadas por esas views;
- RLS puede agregarse como defense-in-depth cuando el modelo de connection roles esté fijado;
- RLS nunca reemplaza Principal/Representation/domain authorization.

Ejemplo conceptual, ejecutado por provisioning y adaptado al deployment:

```sql
-- Semantic interface
GRANT USAGE ON SCHEMA request_read, request_cmd TO request_app;
GRANT SELECT ON ALL TABLES IN SCHEMA request_read TO request_app;
GRANT EXECUTE ON FUNCTION request_cmd.acquire_idempotency(...) TO request_app;

-- SECURITY INVOKER also requires the exact underlying privileges.
-- Grant only the base relations/DML used by the app's repositories and views;
-- do not use blanket production grants merely for convenience.
GRANT SELECT ON request_engine.requests TO request_app;

-- Worker example: EXECUTE plus the exact underlying outbox privileges because
-- claim_outbox_batch is SECURITY INVOKER.
GRANT USAGE ON SCHEMA request_cmd TO request_worker;
GRANT EXECUTE ON FUNCTION request_cmd.claim_outbox_batch(...) TO request_worker;
GRANT SELECT, UPDATE ON request_engine.outbox_messages TO request_worker;
```

No conceder `CREATE` a runtime roles.

Una futura transición de una primitive a `SECURITY DEFINER` deberá ser explícita; no se hará para evitar diseñar correctamente grants/RLS.

---

## 11. Initial read surface

V2.10 establece inicialmente:

```text
request_read.request_summary_v1
request_read.reservation_summary_v1
request_read.payment_requirement_status_v1
request_read.payment_transaction_status_v1
request_read.external_commitment_status_v1
request_read.queue_entry_status_v1
```

Estas views son projections/read contracts. Los campos derivados no sustituyen command validation.

---

## 12. Initial command primitives

V2.10 establece inicialmente:

```text
request_cmd.lock_capacity_authorities
request_cmd.advance_planning_revision
request_cmd.acquire_idempotency
request_cmd.complete_idempotency
request_cmd.claim_outbox_batch
request_cmd.mark_outbox_delivered
request_cmd.release_outbox_claim
```

Cada primitive debe poder ejecutarse dentro de una transaction controlada por SQLAlchemy.

---

## 13. Admin surface

V2.10 establece inicialmente:

```text
request_admin.outbox_health_v1
request_admin.open_reconciliation_v1
```

Son diagnósticos, no authority.

---

## 14. Versioning y migrations

- `request_engine` evoluciona mediante Alembic/migrations revisadas;
- read views incompatibles incrementan `_vN`;
- command function signature incompatible crea nueva signature/name/version explícita antes de retirar consumers antiguos;
- no cambiar silenciosamente la semántica de una view/function ya consumida;
- migrations que alteran append-only facts deben preservar evidence y limitar temporalmente cualquier trigger disable al objeto exacto que requiera backfill;
- role grants se versionan junto al deployment, no se improvisan manualmente en producción.

---

## 15. Testing gate

Antes de considerar congelada la frontera DB/API:

1. aplicar `03 → 04 → 05 → 06 → 08` en PostgreSQL 18 limpio;
2. introspection test de schemas/views/functions;
3. comprobar que ninguna `request_read` view es usada como mutation authority;
4. race tests del catálogo de `02-pre-sql-domain-contract.md`;
5. test de idempotency same-key/same-hash y same-key/different-hash;
6. multi-worker outbox test con `SKIP LOCKED`, crash lease y reclaim;
7. privilege test: `PUBLIC` no ejecuta `request_cmd`;
8. privilege test de `SECURITY INVOKER`: caller sin base privilege falla como corresponde;
9. future RLS test antes de activar tenant-scoped DB roles.

---

## 16. Decision record

### Decisión aceptada

```text
smart PostgreSQL
+ explicit relational integrity
+ stable locks
+ versioned read views
+ narrow command primitives
+ Python-owned Unit of Work and domain orchestration
```

### Alternativas rechazadas

**Dumb database / ORM CRUD only**

Rechazada porque deja races e invariantes críticos a disciplina de application code y desperdicia las garantías relacionales/transaccionales de PostgreSQL.

**Stored-procedure backend**

Rechazada porque duplicaría la application layer en PL/pgSQL, fragmentaría policy/orchestration y dificultaría testing, debugging, observability y evolución de integrations.

**Writable views como command interface**

Rechazadas porque ocultan semántica material detrás de `UPDATE`/`INSERT` genéricos y favorecen triggers de workflow difíciles de razonar.

**Materialized projections como authority**

Rechazadas porque son snapshots refrescables, no current transaction truth.

### Consecuencia intencional

Existe cierta duplicación controlada entre:

```text
DB backstop invariant
and
Python domain validation
```

Esto es deseable cuando Python produce mejores errores/contexto y PostgreSQL conserva la última línea de defensa. No duplicar workflows completos en ambos lenguajes.

---

## 17. Referencias técnicas de la decisión

Fuentes primarias usadas para esta frontera:

- PostgreSQL 18 `CREATE VIEW`: `security_invoker`, seguridad y updateability: https://www.postgresql.org/docs/18/sql-createview.html
- PostgreSQL 18 `CREATE FUNCTION`: volatility, `SECURITY INVOKER/DEFINER`, safe `search_path`: https://www.postgresql.org/docs/18/sql-createfunction.html
- PostgreSQL 18 `CREATE PROCEDURE`: transaction-control/security semantics: https://www.postgresql.org/docs/18/sql-createprocedure.html
- PostgreSQL 18 privileges: default `EXECUTE` para functions/procedures y schema/object grants: https://www.postgresql.org/docs/18/ddl-priv.html
- PostgreSQL 18 materialized views / refresh semantics: https://www.postgresql.org/docs/18/rules-materializedviews.html
- PostgreSQL 18 `REFRESH MATERIALIZED VIEW`: https://www.postgresql.org/docs/18/sql-refreshmaterializedview.html
- SQLAlchemy 2.0 Session/Unit of Work/transaction scope: https://docs.sqlalchemy.org/en/20/orm/session_basics.html
