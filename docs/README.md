# Request Engine — documentación

Este directorio separa explícitamente la **arquitectura V2 vigente** de documentación histórica V1.

## Documentos autoritativos V2

1. [`00-product-definition.md`](00-product-definition.md)
   - definición del producto y boundaries;
   - vocabulario canónico;
   - ownership semántico;
   - invariantes de dominio.

2. [`01-architecture-v2.md`](01-architecture-v2.md)
   - arquitectura técnica objetivo;
   - PostgreSQL/Python/FastAPI;
   - módulos y transaction protocols;
   - concurrency, security, payments, reservations, dispatch y testing.

3. [`02-pre-sql-domain-contract.md`](02-pre-sql-domain-contract.md)
   - cardinalidades normativas;
   - serialization roots;
   - transaction proofs;
   - matriz I01–I76;
   - gate obligatorio previo al freeze relacional.

4. [`07-database-access-contract.md`](07-database-access-contract.md)
   - contrato normativo Python ↔ PostgreSQL;
   - ownership entre Application/Domain y DB;
   - `request_engine` / `request_read` / `request_cmd` / `request_admin`;
   - Unit of Work SQLAlchemy y transaction boundaries;
   - política de views, functions, stored procedures, materialized views y privileges;
   - decision record que explica por qué se rechazaron tanto ORM CRUD/dumb DB como un stored-procedure backend.

`07` complementa `01/02`: estandariza **cómo se usa** el modelo relacional sin redefinir las invariantes del dominio.

## Diseño PostgreSQL

[`03-postgresql-schema.sql`](03-postgresql-schema.sql) es el **reference schema V2.6 para PostgreSQL 18+**.

[`04-postgresql-v2.7-hardening.sql`](04-postgresql-v2.7-hardening.sql) es el delta V2.7 consolidado. Cierra lineage relacional, capacity serialization básica, lifecycle monotónico y backstops financieros sin convertir PostgreSQL en workflow engine.

[`05-postgresql-v2.8-hardening.sql`](05-postgresql-v2.8-hardening.sql) es un delta DBA deliberadamente pequeño sobre V2.7. Corrige orden de locks, hace `CapacityHold` estrictamente monotónico, elimina autoridad duplicada entre trigger inmediato y constraint trigger diferido, y reduce índices redundantes.

[`06-postgresql-v2.9-integrity.sql`](06-postgresql-v2.9-integrity.sql) cierra dos huecos de integridad restantes: hace DB-provable que `FinancialObservation → ObservationCorrection → PaymentAllocationAdjustment` permanezca dentro del mismo `PaymentTransaction`, y materializa coverage tipado `ExternalCommitment → CommitmentRequirement` dentro de la misma `Reservation` en lugar de usar `scope_snapshot` como autoridad.

[`08-postgresql-v2.10-access-surface.sql`](08-postgresql-v2.10-access-surface.sql) implementa la frontera DB↔Python definida en `07` como un único delta V2.10 consolidado: schemas de interface, read views versionadas, command primitives estrechas, idempotency, outbox con `SKIP LOCKED` + lease fencing token, deny-by-default para `request_cmd` y `search_path` seguro para routines reutilizables.

Aplicación actual:

```text
03-postgresql-schema.sql
        ↓
04-postgresql-v2.7-hardening.sql
        ↓
05-postgresql-v2.8-hardening.sql
        ↓
06-postgresql-v2.9-integrity.sql
        ↓
08-postgresql-v2.10-access-surface.sql
```

`07-database-access-contract.md` es documentación normativa y por eso no aparece como migration dentro de la cadena SQL.

## Frontera PostgreSQL ↔ Python

La decisión vigente es:

```text
FastAPI / Worker / Agent adapter
            ↓
     Application layer
            ↓
  SQLAlchemy Unit of Work
            ↓
 ┌──────────┴──────────┐
 │                     │
COMMAND               QUERY
 │                     │
repositories +     request_read.*
request_cmd.*      versioned views
 │                     │
 └──────────┬──────────┘
            ↓
     request_engine.*
 authoritative tables
```

Reglas esenciales:

- Python conserva ownership de commands, business policy, authorization, external I/O y transaction orchestration;
- PostgreSQL conserva structural truth, row locking, local invariants, idempotency, facts, audit y outbox;
- `request_cmd` contiene primitives data-centric estrechas, no workflows completos;
- `request_read` contiene views read-only/versionadas; no se escribe negocio a través de views;
- materialized views sólo podrán aparecer como projections medidas, nunca como mutation authority;
- no network calls ni hidden business transaction control dentro de PostgreSQL routines;
- un command autoritativo usa una SQLAlchemy Session/Unit of Work y una DB transaction coherente con el lock order de `02`.

## Principios físicos vigentes

- claves internas `bigint identity` y public IDs UUIDv7;
- foreign keys tenant-aware con `organization_id`;
- typed relationships para lineage crítico;
- `OutcomeScope` como serialization root de outcome mutable;
- `CapacityAuthority` como stable lock root de capacidad;
- common `CapacityClaim` conflict space para Holds y Allocations;
- intervalos `[start,end)` con `tstzrange`;
- consumo histórico con semántica replace-don't-rewrite;
- al confirmar o reprogramar, un `CapacityClaim` puede reemplazarse atómicamente por otro preservando `replaced_by_capacity_claim_id` y `ResourceAllocation.source_capacity_hold_id`; no se reescribe la prueba histórica de adquisición;
- facts financieros/outcome/audit append-oriented;
- `scope_snapshot` y otros JSON históricos son evidencia/provenance, no sustitutos de FKs cuando una relación participa en autoridad o invariantes;
- constraints antes que triggers cuando PostgreSQL puede expresar la regla declarativamente;
- triggers pequeños sólo para monotonicidad, inmutabilidad local, revisions y backstops agregados;
- constraint triggers diferidos sólo cuando la cardinalidad debe comprobarse al final de la transacción;
- command transactions para invariantes multi-root, policy-dependent o dependientes de autoridad externa;
- views de `request_read` son contracts de lectura, no security/authorization por sí solas;
- functions de `request_cmd` usan `SECURITY INVOKER` por defecto y `PUBLIC` no recibe `EXECUTE`;
- routines reutilizables fijan `search_path` para no depender de resolución de nombres controlada por sesión;
- outbox leases usan `claim_token` por adquisición; `worker_id` es identidad diagnóstica, no fencing authority;
- deployment roles/RLS se diseñan juntos cuando quede fijado el modelo de conexiones; RLS será defense-in-depth, nunca sustituto de Principal/Representation authorization;
- índices únicamente cuando corresponden a predicates/joins realmente calientes y no estén ya implícitos en PK/UNIQUE constraints.

El SQL no sustituye los command protocols de `02-pre-sql-domain-contract.md`. Una pre-validación fuera de la transacción documentada nunca es autoridad.

## Prioridad conceptual

Si dos artefactos parecen contradecirse, la prioridad es:

```text
00-product-definition.md
        ↓
01-architecture-v2.md
        ↓
02-pre-sql-domain-contract.md
        ↓
07-database-access-contract.md
        ↓
03/04/05/06/08 PostgreSQL migrations
```

`07` no puede relajar una invariante de `02`; sólo define cómo Application/Repositories/Query Services consumen correctamente PostgreSQL.

El schema implementa el contrato; no puede redefinir silenciosamente el dominio. Cuando el SQL elige replacement en vez de update in-place, la equivalencia arquitectónica exige lineage explícita y una transición atómica bajo el mismo command protocol.

## Lecciones V1 y archivo histórico

[`02-v1-lessons-preserved.md`](02-v1-lessons-preserved.md) conserva lecciones V1 útiles para migración, pero no tiene precedencia sobre el contrato V2.

[`v1-ideas-viejas/`](v1-ideas-viejas/) contiene documentos preservados exclusivamente como contexto histórico.

No utilizar archivos históricos como especificación actual. Pueden contener vocabulario antiguo (`booking`), arquitectura Convex, endpoints/workflows que ya no representan V2 o decisiones verticales retiradas del core.

Cuando una idea histórica siga siendo útil, debe aparecer sintetizada en un documento V2 vigente antes de implementarse nuevamente.
