# Architecture Decision Records

ADRs capture durable, hard-to-reverse architectural decisions. They explain **why** a constraint exists; canonical domain/transaction documents remain authoritative for detailed invariants and protocols.

Use an ADR when changing module boundaries, Python/PostgreSQL ownership, deployment/migration strategy, cross-module contracts, security/isolation posture, or another decision future maintainers are likely to question.

Format:

```text
# NNNN — Title
Status: Proposed | Accepted | Superseded

## Context
## Decision
## Consequences
## Rejected alternatives
```

Do not create ADRs for ordinary implementation choices that are easy to reverse.

Current records:

- `0001-modular-monolith.md`
- `0002-smart-postgresql-boundary.md`
- `0003-module-first-python-layout.md`
- `0004-agent-knowledge-system.md`
- `0005-capability-first-product-core.md`
- `0006-durable-transactional-communications.md`
- `0007-minimal-booking-capacity-model.md`
- `0008-tenant-rls-runtime-isolation.md`
- `0009-v3-database-contract-convergence.md`
- `0010-reservation-access-delivery-boundary.md` — proposed boundary to be accepted only after the ReservationAccess implementation and evidence prove it.
- `0011-cross-tenant-identity-and-shared-capacity.md` — proposed post-freeze direction; not part of the V3 baseline.
- `0012-contextual-resource-location-supply.md` — accepted post-V3 Resource-at-Location/contextual booking-supply architecture, proven by PR #75 exact-head CI and integrated into `development` on 2026-08-22.
- `0013-identity-security-decision-gates.md` — accepted D1–D6 security decision gates for identity recovery, secret delivery, linking, continuity, topology serialization and operational acceptance.
- `0014-instance-claim-platform-owner-trust-root.md` — accepted self-hosted Instance claim/Platform Owner trust root; supersedes the CLI-first bootstrap assumption while preserving ADR 0013 recovery, continuity and serialization guarantees.
- `0015-platform-configuration-secrets-recovery.md` — accepted self-hosted configuration/secret-store boundary: OpenBao reference backend, provider-neutral secret contract and an OpenBao-independent offline Platform Owner recovery path.
- `0016-existing-controller-policy-adoption.md` — accepted; implementation in progress: manifest-bounded dual-consent governance for existing tenant roots; preserves ordinary delegation/self-upgrade guarantees and forbids automatic/backfill grants.
- `0017-optional-passkeys-administrative-authentication.md` — accepted product-owner evolution: optional passkeys for claim and recent password or WebAuthn proof for administrative confirmation; implementation and evidence in progress.
- `0018-mcp-tool-gateway.md` — accepted (2026-10-19, product-owner request): stateless MCP Streamable HTTP adapter on the tenant runtime that projects explicitly tool-marked owner operations from the caller's current authorized catalog and executes them by re-entering the same API; no second execution path or LLM runtime.
- `0019-agent-proposed-staff-invitations.md` — accepted product-owner request (2026-10-19): agents propose staff invitations under operational `staff.propose_invitation`; only a recently authenticated HUMAN `staff.invite` manager approves or rejects; controller policy v8.
- `0020-external-ui-client-and-change-feed.md` — accepted product-owner request (2026-10-22): the user interface is the external `request-engine-app` client (BFF holds tokens, no browser CORS); the Jinja console retires at parity; `GET /v1/changes/stream` is an invalidation-only SSE change feed with a `pg_snapshot` cursor.
