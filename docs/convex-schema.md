# Convex Schema

Initial tables:

- `tenants`
- `channels`
- `aiStates`
- `catalogItems`
- `knowledgeItems`
- `requests`
- `requestEvents`
- `appointments`
- `quotes`
- `integrationConnections`
- `webhookEvents`

Business tables include `tenantId` where they represent tenant-owned data. Chatwoot-linked tables store `chatwootAccountId` when applicable. Webhook events include `eventKey` for idempotency.
