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

[`04-postgresql-v2.7-hardening.sql`](04-postgresql-v2.7-hardening.sql) es el delta V2.7 consolidado. Cierra lineage relacional, capacity serialization básica, lifecycle monotónico y backstops financieros sin convertir PostgreSQL en workflow engine.

[`05-postgresql-v2.8-hardening.sql`](05-postgresql-v2.8-hardening.sql) es un delta DBA deliberadamente pequeño sobre V2.7. Corrige orden de locks, hace `CapacityHold` estrictamente monotónico, elimina autoridad duplicada entre trigger inmediato y constraint trigger diferido, y reduce índices redundantes.

Aplicación actual:

```text
03-postgresql-schema.sql
        ↓
04-postgresql-v2.7-hardening.sql
        ↓
05-postgresql-v2.8-hardening.sql
```

Principios físicos vigentes:

- claves internas `bigint identity` y public IDs UUIDv7;
- foreign keys tenant-aware con `organization_id`;
- typed relationships para lineage crítico;
- `OutcomeScope` como serialization root de outcome mutable;
- `CapacityAuthority` como stable lock root de capacidad;
- common `CapacityClaim` conflict space para Holds y Allocations;
- intervalos `[start,end)` con `tstzrange`;
- consumo histórico con semántica replace-don't-rewrite;
- facts financieros/outcome/audit append-oriented;
- constraints antes que triggers cuando PostgreSQL puede expresar la regla declarativamente;
- triggers pequeños sólo para monotonicidad, inmutabilidad local, revisions y backstops agregados;
- constraint triggers diferidos sólo cuando la cardinalidad debe comprobarse al final de la transacción;
- command transactions para invariantes multi-root, policy-dependent o dependientes de autoridad externa;
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
03-postgresql-schema.sql
        ↓
04-postgresql-v2.7-hardening.sql
        ↓
05-postgresql-v2.8-hardening.sql
```

El schema implementa el contrato; no puede redefinir silenciosamente el dominio.

## Lecciones V1 y archivo histórico

[`02-v1-lessons-preserved.md`](02-v1-lessons-preserved.md) conserva lecciones V1 útiles para migración, pero no tiene precedencia sobre el contrato V2.

[`v1-ideas-viejas/`](v1-ideas-viejas/) contiene documentos preservados exclusivamente como contexto histórico.

No utilizar archivos históricos como especificación actual. Pueden contener vocabulario antiguo (`booking`), arquitectura Convex, endpoints/workflows que ya no representan V2 o decisiones verticales retiradas del core.

Cuando una idea histórica siga siendo útil, debe aparecer sintetizada en un documento V2 vigente antes de implementarse nuevamente.
