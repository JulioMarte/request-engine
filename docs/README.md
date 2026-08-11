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

## Diseño PostgreSQL

[`03-postgresql-schema.sql`](03-postgresql-schema.sql) es el **reference schema V2.6 para PostgreSQL 18+**.

El archivo traduce el contrato pre-SQL a un modelo físico con:

- claves internas `bigint identity` y public IDs UUIDv7;
- foreign keys tenant-aware con `organization_id`;
- typed relationships en lugar de referencias polimórficas críticas;
- `OutcomeScope` como serialization identity;
- common `CapacityClaim` conflict space para holds y allocations;
- intervalos `[start,end)` con `tstzrange`;
- hechos outcome/financial/audit append-oriented;
- guards transaccionales para capacity, fulfillment budgets y financial allocation budgets;
- transactional outbox e idempotency persistence.

El SQL no sustituye los command protocols de `02-pre-sql-domain-contract.md`. Las invariantes que dependen de múltiples aggregates, schedules variables, external authority o recovery conservan un lock/application protocol explícito sobre las mismas autoridades estables.

## Prioridad conceptual

Si dos artefactos parecen contradecirse, la prioridad es:

```text
00-product-definition.md
        ↓
01-architecture-v2.md
        ↓
02-pre-sql-domain-contract.md
        ↓
03-postgresql-schema.sql
```

El schema implementa el contrato; no puede redefinir silenciosamente el dominio.

## Lecciones V1 y archivo histórico

[`02-v1-lessons-preserved.md`](02-v1-lessons-preserved.md) conserva lecciones V1 útiles para migración, pero no tiene precedencia sobre el contrato V2.6.

[`v1-ideas-viejas/`](v1-ideas-viejas/) contiene documentos preservados exclusivamente como contexto histórico.

No utilizar archivos históricos como especificación actual. Pueden contener vocabulario antiguo (`booking`), arquitectura Convex, endpoints/workflows que ya no representan V2 o decisiones verticales retiradas del core.

Cuando una idea histórica siga siendo útil, debe aparecer sintetizada en un documento V2 vigente antes de implementarse nuevamente.
