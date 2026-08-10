# Request Engine — documentación

Este directorio separa explícitamente la **arquitectura V2 vigente** de documentación histórica V1.

## Documentos autoritativos V2

1. [`00-product-definition.md`](00-product-definition.md)
   - definición del producto;
   - vocabulario canónico;
   - boundaries;
   - invariantes de dominio;
   - resultados del stress test de casos edge.

2. [`01-architecture-v2.md`](01-architecture-v2.md)
   - arquitectura técnica objetivo;
   - PostgreSQL/Python/FastAPI;
   - módulos, commands/queries, concurrency, security, payments, reservations, dispatch y testing.

3. [`02-v1-lessons-preserved.md`](02-v1-lessons-preserved.md)
   - lecciones V1 que siguen siendo válidas;
   - security/outbox/holiday/queue lessons;
   - estrategia de migración Convex V1 → PostgreSQL V2;
   - decisiones V1 que explícitamente NO se preservan.

Si dos documentos V2 parecen contradecirse, la prioridad conceptual es:

```text
00-product-definition.md
        ↓
01-architecture-v2.md
        ↓
02-v1-lessons-preserved.md
```

`02` complementa los dos primeros; no puede redefinir el producto.

## Archivo histórico

[`v1-ideas-viejas/`](v1-ideas-viejas/) contiene documentos preservados exclusivamente para consultar contexto histórico.

No utilizar archivos de ese directorio como especificación actual. Pueden contener:

- vocabulario antiguo (`booking`);
- arquitectura Convex;
- endpoints/workflows que ya no representan V2;
- referencias operacionales fechadas;
- decisiones verticales/healthcare que fueron retiradas del core.

Cuando una idea histórica siga siendo útil, debe aparecer sintetizada en un documento V2 antes de implementarse nuevamente.
