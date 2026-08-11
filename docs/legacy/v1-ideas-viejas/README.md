# V1 — ideas viejas / archivo histórico

> **NO AUTORITATIVO PARA V2.**

Este directorio conserva documentación de la implementación V1 para investigación, migración y trazabilidad histórica.

## Contenido

- [`scheduling-v1.md`](scheduling-v1.md): arquitectura de agenda Convex V1, incluyendo invariantes y decisiones verticales de aquella implementación.
- [`handoff-2026-07-31.md`](handoff-2026-07-31.md): snapshot operacional del 31 de julio de 2026 para Convex, Chatwoot, Evolution y n8n.

## Reglas de uso

1. No implementar directamente desde estos documentos.
2. No reutilizar endpoints, workflow IDs, URLs, secret names o instrucciones operacionales sin verificar el estado actual.
3. No reintroducir `booking` como vocabulario de dominio: V2 usa `Reservation`.
4. No asumir que Convex, n8n, Chatwoot o Evolution son componentes obligatorios de V2.
5. Si una idea histórica parece útil, comprobar primero si ya está incorporada en los documentos V2.

Las lecciones V1 consideradas vigentes están sintetizadas en [`../02-v1-lessons-preserved.md`](../02-v1-lessons-preserved.md).

La documentación autoritativa comienza en [`../README.md`](../README.md).
