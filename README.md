# Request Engine

Motor multiempresa de agenda, clases y orden de llegada diseñado para ser operado por agentes de IA y por un panel humano. Convex es la fuente de verdad transaccional; Chatwoot conserva las conversaciones y n8n funciona como adaptador temporal de automatización.

## Estado de la implementación

- Dominio v1 estricto para organizaciones, sedes, personas, tutores, seguros, recursos, calendarios, excepciones, citas, clases, colas, prompts, credenciales y auditoría.
- Disponibilidad calculada bajo demanda, con ofertas opacas de cinco minutos y máximo cinco opciones por llamada.
- Reserva serializable con revalidación de capacidad/recursos, snapshot comercial e idempotencia.
- Citas `fixed_time`, ventanas `arrival_window` y sesiones `class_session`.
- Confirmaciones multicanal, outbox con reintentos y liberación segura de citas no confirmadas.
- Check-in transaccional, ticket estable y estimación de espera explícitamente no garantizada.
- REST `/v1` mediante Convex HTTP Actions y contrato OpenAPI 3.1.
- API keys propias con hash, scopes, expiración, revocación y separación por organización.
- PII sensible cifrada con AES-GCM, índice ciego HMAC y valor enmascarado.
- Panel operativo React para agenda, cola y runtime de agentes.

Las tablas originales (`tenants`, `requests`, `appointments`, etc.) siguen presentes como legado de solo migración. No se borran hasta verificar equivalencia y conteos.

## Desarrollo

```bash
npm install
npm run test
npm run lint
npm run build
```

Para validar y desplegar las funciones en el deployment de desarrollo:

```bash
npm run typecheck:convex
```

## Configuración

Los valores `VITE_` son públicos. Todos los secretos pertenecen al entorno de Convex, nunca al frontend.

```txt
VITE_CONVEX_URL=
VITE_CLERK_PUBLISHABLE_KEY=

PLATFORM_BOOTSTRAP_SECRET=
PII_ENCRYPTION_KEY=
PII_BLIND_INDEX_KEY=
INTEGRATION_WEBHOOK_SECRET=
N8N_OUTBOX_WEBHOOK_URL=
N8N_OUTBOX_WEBHOOK_SECRET=
```

El primer alta usa `POST /v1/onboarding/organizations` con `X-Bootstrap-Secret`. Después se emite una API key una sola vez mediante `POST /v1/api-keys`. La empresa permanece en `draft` hasta una publicación explícita.

## API para agentes

El documento se sirve en `GET /v1/openapi.json`. El flujo obligatorio de reserva es:

1. `catalog.search`
2. `availability.summarize`
3. `availability.listOptions`
4. `booking.create` con `offerId` e `Idempotency-Key`

Los agentes no reciben calendarios ni catálogos completos en el prompt. `GET /v1/agent/runtime-bundle` entrega prompts publicados, manifest de tools y hasta cinco pistas de catálogo.

Consulta [arquitectura v1](docs/scheduling-v1.md) para invariantes, seguridad, integraciones y migración.
