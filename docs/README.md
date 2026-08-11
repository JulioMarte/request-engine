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

[`04-postgresql-v2.7-hardening.sql`](04-postgresql-v2.7-hardening.sql) es el **delta V2.7 consolidado** y se aplica directamente después de `03`. No existe una cadena adicional de parches para V2.7.

V2.7 endurece el modelo físico sin convertir PostgreSQL en un workflow engine:

- composite foreign keys tenant-aware para lineage crítico;
- `OutcomeScope` como serialization root para `reject_excess`;
- `CapacityAuthority` como lock root estable para consumo local;
- liberación de capacidad independiente de revisions históricas obsoletas;
- `ResourceAllocation` y `CapacityClaim` con semántica replace-don't-rewrite;
- cardinalidad Allocation ↔ active CapacityClaim validada al final de la transacción;
- schedule/config revisions locales y `PlanningRevision` controlada por command;
- guards financieros mínimos para over-allocation/reconciliation y refunds concurrentes;
- índices sólo para rutas de validación calientes no cubiertas ya por constraints.

El SQL no sustituye los command protocols de `02-pre-sql-domain-contract.md`. Las invariantes multi-root, policy-dependent o dependientes de autoridad externa permanecen en transacciones de aplicación con lock order documentado.

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
```

El schema implementa el contrato; no puede redefinir silenciosamente el dominio.

## Lecciones V1 y archivo histórico

[`02-v1-lessons-preserved.md`](02-v1-lessons-preserved.md) conserva lecciones V1 útiles para migración, pero no tiene precedencia sobre el contrato V2.

[`v1-ideas-viejas/`](v1-ideas-viejas/) contiene documentos preservados exclusivamente como contexto histórico.

No utilizar archivos históricos como especificación actual. Pueden contener vocabulario antiguo (`booking`), arquitectura Convex, endpoints/workflows que ya no representan V2 o decisiones verticales retiradas del core.

Cuando una idea histórica siga siendo útil, debe aparecer sintetizada en un documento V2 vigente antes de implementarse nuevamente.
