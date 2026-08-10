# Request Engine

Request Engine está evolucionando de un MVP V1 centrado en scheduling/Convex hacia una arquitectura V2 más general: un **motor transaccional headless y multiempresa que transforma intención en workflows deterministas, commitments de capacity, pagos verificables y resultados auditables**.

## Estado del repositorio

### Implementación heredada V1

El código existente contiene un MVP funcional construido principalmente con React/Vite/TypeScript/Convex. Incluye scheduling, resources, queues, holidays, APIs y varias integraciones experimentales.

Ese código es **legacy útil para migración y aprendizaje**, pero ya no define por sí solo el producto ni la arquitectura objetivo.

No asumir que:

- Convex seguirá siendo el source of truth de V2;
- `booking` es vocabulario vigente;
- Chatwoot, Evolution o n8n son dependencias obligatorias;
- modelos específicos de healthcare pertenecen al core;
- la documentación V1 describe el target actual.

### Arquitectura objetivo V2

La foundation V2 actualmente adoptada favorece:

- PostgreSQL como source of truth transaccional;
- Python + FastAPI;
- SQLAlchemy + Alembic;
- modular monolith;
- API y workers como procesos separados sobre el mismo dominio;
- transactional outbox;
- API-first/headless;
- multi-tenancy explícito;
- REST/OpenAPI + tools para agentes sobre el mismo application layer;
- `Reservation` como vocabulario canónico de capacity commitment;
- payments provider-agnostic con verificación financiera explícita;
- integrations externas como adapters, no owners del dominio.

## Documentación

La entrada oficial es [`docs/README.md`](docs/README.md).

Documentos V2 autoritativos:

1. [`docs/00-product-definition.md`](docs/00-product-definition.md) — definición del producto y dominio.
2. [`docs/01-architecture-v2.md`](docs/01-architecture-v2.md) — arquitectura técnica objetivo.
3. [`docs/02-v1-lessons-preserved.md`](docs/02-v1-lessons-preserved.md) — lecciones V1 preservadas y estrategia de migración.

Documentación histórica V1:

- [`docs/v1-ideas-viejas/`](docs/v1-ideas-viejas/)

Los documentos del archivo histórico no deben utilizarse como especificación vigente.

## Desarrollo del código V1 existente

Mientras el código legacy siga presente, sus comandos actuales pueden seguir siendo útiles para inspección/migración:

```bash
npm install
npm run test
npm run lint
npm run build
```

Antes de ejecutar comandos de Convex, provisioning o integraciones históricas, revisar el archivo V1 y validar que el entorno/credenciales continúan siendo correctos. No imprimir ni copiar secretos a Git, logs o conversaciones.

## Regla de evolución

Las nuevas decisiones de dominio deben documentarse primero contra la foundation V2 y probarse mediante invariantes/casos edge. El código V1 se migra o reemplaza deliberadamente; no debe arrastrar accidentalmente sus boundaries al diseño nuevo.
