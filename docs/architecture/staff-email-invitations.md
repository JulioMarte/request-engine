# Staff email invitations

Status: implementation under verification; not yet publication evidence.

## Ownership and authority

Tenancy owns the invitation and acceptance membership. Communications owns the
closed-purpose address delivery intent and worker. An unregistered recipient is
not a patient Party and no contact verification is fabricated. Bootstrap injects
Communications' recorder into a caller-owned Tenancy outbound port; there is no
Tenancy Python import of Communications and no dependency cycle through Booking.

Invitation creation confers no membership or grants. Acceptance requires a real
native HUMAN session plus possession of a random, expiring proof; email matching
is never identity authentication. Native enrollment/login remains canonical.
OIDC acceptance is intentionally not supported in this slice.

Acceptance creates active membership with zero standing grants. An administrator
uses the existing authority preview/apply APIs afterward. The invitation's
destination is not copied into an identity profile or verified recovery address.

## Operation design gate

| Method and path | Stable operationId | Authority | Semantics |
|---|---|---|---|
| POST `/v1/staff/invitations` | `staff_invitation_create` | `staff.invite`, HUMAN | Create expiring invitation; Idempotency-Key |
| GET `/v1/staff/invitations` | `staff_invitation_list` | `staff.read`, HUMAN | Bounded keyset read, no token |
| GET `/v1/staff/invitations/{invitation_id}` | `staff_invitation_get` | `staff.read`, HUMAN | Tenant-opaque detail, no token |
| POST `/v1/staff/invitations/{invitation_id}:resend` | `staff_invitation_resend` | `staff.invite`, HUMAN | Revisioned, idempotent new proof generation |
| POST `/v1/staff/invitations/{invitation_id}:revoke` | `staff_invitation_revoke` | `staff.invite`, HUMAN | Revisioned, idempotent terminal revoke |
| POST `/v1/staff/invitations/{invitation_id}:accept` | `staff_invitation_accept` | Native subject + proof | Subject/result-bound replay; rejects tenant selector |

Owner is Tenancy for all six operations. Reads require no idempotency/revision.
Create takes email, bounded lifetime and provenance. Resend/revoke take current
revision and provenance. Acceptance takes only the proof envelope. Tools are not
projected: these are human identity and secret-possession operations. Input schemas
reject extra trusted identity fields. Admin DTOs expose lifecycle, revision,
expiry, generation and delivery state, never plaintext proof or secret reference.

Admin idempotent replay returns the same invitation identifier with its current
representation, not a frozen historic status. After revoke, replaying create must
not show a misleading pending invitation. The original command fingerprint and
audit receipt remain durable; conflicting reuse fails and replay never stages or
queues another proof. Accepted subject replay retains original membership IDs.

Preserved guarantees: INV-TENANT-001, INV-AUTHORITY-001, INV-ATOMICITY-001,
INV-IDEMPOTENCY-001, INV-PROVENANCE-001, INV-WORKER-001, INV-OUTBOX-001 and
INV-PRIVILEGE-001. Current controller continuity remains unchanged.

## Transactions and delivery

READ/PLAN validates normalized destination, expiry and trusted subject/actor.
Secret staging occurs before authoritative locks. LOCK/VALIDATE uses the shared
identity-topology gate, canonical ordered staff roots, invitation and native
identity/session roots; current inviter authority, tenant and session are checked
again. WRITE/EMIT commits invitation plus delivery intent and scheduled action in
one transaction. Acceptance binds its original result to the accepting identity;
another identity cannot reuse that result. No inviter ActorContext is fabricated.

Migration `0010_invitation_topology_gate` strengthens the materialization entry:
its first statement directly acquires the existing shared identity-topology gate,
before delegating to the proof/session lock function that also acquires that gate.
The repeated acquisition is transaction-local; lock roots/order, grants and
acceptance semantics do not change. This is an additive function replacement,
not a data backfill or table rewrite. Published 0009 and the baseline are immutable.
Downgrade restores 0009's delegated gate; rolling forward restores the stronger
direct-entry contract. The complete topology writer inventory and independent
connection blocking proof now include this eight-argument command. KEEP the
first-statement/lock-order assertions; extend their scope, do not exempt the writer.

PostgreSQL's narrow materialization backstop independently rechecks proof/session
and atomically establishes the linked principal, binding, zero-grant membership,
acceptance receipt and provenance. A mutable transaction GUC alone cannot invoke
it. Python owns command orchestration, delivery-intent composition, staging,
admin idempotency and lifecycle intent; this is not a database email workflow or
a second owner implementation.

The secret store retains `<invitation UUID>.<random proof>` with TTL. PostgreSQL
retains only a SHA256 digest and opaque reference. Proofs never enter ordinary
audit/outbox payloads or administrative responses. Resend rotates the digest;
revoked, expired and superseded proofs cannot activate membership.

The delivery worker commits attempting before external I/O, then finalizes under
the current action lease/fence. Definitive non-transmission failures may retry;
uncertain outcomes reconcile first with the same deterministic provider key.
SMTP cannot query delivery, so unresolved uncertainty never triggers blind resend.
Bounded attempts leave visible unknown state. A successful SMTP response means
mail-server acceptance, not inbox arrival, receipt or reading.

Cancel and prepare serialize on the delivery row. Cancellation fences pending
and unfinished generations; finalize cannot overwrite cancelled. An already
prepared network send may finish after revoke/accept/resend. The old proof is
invalid, but no claim is made that in-flight mail can be recalled.

## Deployment and panel

Configure `REQUEST_ENGINE_STAFF_INVITATION_ACCEPT_URL` to the console's
`https://<console-host>/staff-invitations`. Only loopback development may use HTTP.
Configure the existing governed OpenBao/Vault store and acceptance URL in the
runtime and worker. HTTP receives only `RecoverySecretStaging` (stage/discard);
it does not resolve provider configuration or require fallback SMTP variables.
Missing governed retention or acceptance URL keeps creation fail-closed.

The worker receives the full delivery port and resolves API-managed ACTIVE SMTP
immediately before sending, with explicit bootstrap SMTP as optional fallback.
The HTTP application role retains no runtime provider-read privilege. Staging
availability is not SMTP readiness: unavailable transport leaves a visible
delivery failure/retry state, never a fabricated successful email outcome.
Recovery factory overrides are not silently reused with invitation wording/links.

SMTP links use `/staff-invitations/{id}/accept#token=...`. The console clears the
fragment immediately, retains the proof only for the tab's login/enrollment
roundtrip and submits it via same-origin CSRF-protected POST. Runtime acceptance
receives the session bearer without an organization header. The BFF never writes
membership or delivery state directly. Pending/delivery failures are explicit;
UUID-based existing-identity addition remains a distinct advanced operation.

One normalized ASCII mailbox is supported, not recipient lists, display names,
quoted local parts or internationalized addresses. Existing identity-link conflicts
return `staff_invitation_identity_already_linked` (409, not retryable): review the
existing membership/permissions; resending does not restore suspended access.
Failed or concurrent staging can leave a provider-side candidate until expiry.
Do not discard by generation after a transaction failure: it could delete another
transaction's retained winner. Provider TTL metadata is best-effort in the current
store adapters; production retention/cleanup must be verified operationally.

## Proof and limitations

Required falsifiers: tenant opacity; extra identity input; stale revisions;
conflicting idempotency; expiry and rotated proofs; current inviter revocation;
session revocation/global identity disable; same/different accepting identity;
accept-versus-resend/revoke races; delivery-intent transaction rollback; worker
lease loss, cancellation and unknown-outcome replay. PostgreSQL 18 proof must
execute with restricted application/worker LOGIN roles and independent concurrent
connections, not a superuser-only happy path.

Actual evidence and remaining gaps are recorded in
`docs/testing/admin-api-verification-2026-09-30.md`. No external email reception,
authenticated browser proof or production readiness is implied by unit tests.
