# 0013 — Identity security decision gates

Status: Accepted (2026-09-14)

## Context

`docs/architecture/auth-production-completion-plan.md` defines six decision gates
(D1–D6) that block governed identity recovery, secure secret delivery, identity
linking, controller continuity, identity-topology serialization and production
acceptance. Implementing those surfaces without an explicit owner decision would
encode unratified security policy.

The repository owner ratified D1–D6 with the plan's recommended defaults on
2026-09-14. This ADR records that acceptance. Operational details that require a
real environment (D6) remain to be named at deployment and are not invented here.

## Decision

- **D1 Recovery control** — global native identity recovery runs only on the
  private control plane, requires an explicit HUMAN security authority, and the
  approver must differ from the requester. Being a tenant provisioner does not
  grant recovery authority. How those authorities are initially obtained must be
  an explicit, auditable ceremony.
- **D2 Secret delivery** — reset secrets are staged in a dedicated secret store
  with TTL and published through a previously verified channel. Reset secrets
  never appear in audit records, ordinary outbox payloads, logs or administrative
  responses. Ambiguous delivery results are reconciled, never blindly retried.
- **D3 Linking** — v1 linking is self-service only, requires fresh proof of both
  identities, and never merges by email or performs arbitrary administrative
  linking.
- **D4 Continuity** — every tenant and platform plane must retain at least one
  effective controller with an authenticatable path. A controller requires an
  active principal, an active membership (tenant plane), current control grants
  and an active binding to an active authority; native subjects additionally
  require an active identity and password credential. Authority suspension is
  reversible; native identity disable is terminal. Break-glass requires a
  separate, accepted, auditable deployment path.
- **D5 Serialization** — a transactional identity-topology advisory gate precedes
  existing row locks: SHARE for local binding/control/reachability changes,
  EXCLUSIVE for global disable or global authority modification. It must cover
  every writer and be proven free of lock-order inversions before global
  operations ship.
- **D6 Operations** — native-only deployment first, private control plane
  separated, configuration fail-closed. The concrete environment, DNS/TLS/ingress,
  RPO/RTO/SLO, secret manager, delivery channel, operators and deployment approval
  must be named before production acceptance; this ADR does not name them.

Defaults recorded as testable parameters: reauthentication proof ≤5 minutes,
recovery proof ≤30 minutes, approval ≤24 hours, pagination default 50 / maximum
100, case reference ≤400 characters and never clinical text, PII or credentials.
They may be adjusted only by a newer accepted contract.

## Consequences

- Block A and the tenant plane of B2 were implemented under this acceptance;
  their evidence is tracked in `architecture/auth-implementation-status.md`.
- C, D, E and G may proceed without re-litigating D1–D6, but each still needs its
  own contract where the plan requires one (for example D5's complete writer
  inventory and inversion proof).
- Platform-plane continuity (B5) must apply the same D4 predicate to platform
  controllers; the tenant-plane predicate alone is not sufficient.
- D6 remains partially open until the real environment is named; no deployment is
  authorized by this ADR.

## Rejected alternatives

- Enabling recovery, linking or global disable with implicit defaults: rejected
  because it would fabricate security policy and audit obligations.
- A universal `force` capability or an omnipotent support principal: rejected by
  the plan and this decision.
- Counting grants without an authenticatable path: rejected by D4; replaced for
  tenant controllers by revision0042.
