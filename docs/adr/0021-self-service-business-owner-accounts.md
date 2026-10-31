# 0021 — Self-service business owner accounts

Status: Accepted (2026-10-25), by explicit product-owner request, **only within the
change that introduces migration `0006_self_service_accounts`**. Acceptance
is a design decision, not deployment or exact-head CI certification.
Owner: Tenancy.

## Context

The product owner decided:

> Common business owners must be able to create their businesses, because that is
> what they will administer. The local business owner who will pay us is invited —
> by a WhatsApp code or by email — and then follows a setup wizard to create their
> first business and add collaborators.

Before this decision only a platform Principal holding `organization.provision`
could create an Organization (`platform_native_organization_create`), and the
platform administrator had to prepare the future owner's native identity, which in
practice meant choosing and typing that person's password. That is a credential
custody defect: a password chosen by another human is not a proof of the owner.

The authority model (`docs/architecture/principal-agent-and-provisioning-authority-model.md`)
keeps three planes: platform, tenant control and operational. A platform
provisioner never becomes tenant staff by creating a tenant (§23), a tenant
controller never creates unrelated Organizations (§6.2) and routine tenant creation
should prefer "one-time or tightly controlled provisioning intents" over an
omnipotent secret (§22). The business owner who pays is a fourth kind of actor: a
human who will **control** the businesses they create, but who has no Organization
yet and therefore no tenant Principal, and who must never hold platform authority.

## Decision

### 1. Owner account invitation (platform plane, control plane HTTP)

A HUMAN platform Principal holding the existing platform capability
`organization.provision` issues an **account invitation**. No new platform
capability is introduced: an invitation is a bounded, delegated
organization-provisioning intent, so only a holder of organization-creation
authority may issue it (no authority amplification, §21). Reads use the existing
query capability `platform.organization.read`.

An invitation records the issuing platform Principal, a delivery channel, the
organization limit it will grant (`max_organizations`, 1..10, default 1), an
expiry (1..168 hours, default 72), provenance, idempotency/intent digests and
a revision. PostgreSQL stores only the SHA-256 digest and a 16-hex fingerprint of a
random 256-bit token; the raw token exists only in the issuing request.

* `delivery = "shared_code"`: the raw token is returned **once** to the issuing
  administrator (idempotent replay returns `invitation_token = null`) so it can be
  shared as a code or link through WhatsApp or any other channel.
* `delivery = "email"`: the raw token is never returned. After the invitation
  commits, outside every database lock, the control plane sends one email through
  the existing SMTP adapter (managed ACTIVE SMTP with optional bootstrap fallback,
  behind the outbound side-effect fence). When no mailer is composed (no
  `REQUEST_ENGINE_ACCOUNT_INVITATION_ACCEPT_URL`, or no SMTP), creation fails
  closed with a typed `503 account_invitation_delivery_unavailable` before any
  state is written. The delivery outcome (`sent`, `failed`, `unknown`) is recorded
  once as an append-only fact; it is never retried blindly. This follows the
  verified-recovery-address posture (digest only in PostgreSQL, synchronous SMTP)
  rather than the staff-invitation secret-store/worker path, because an account
  invitation has no Organization and therefore no tenant Communications intent.

Pending invitations can be revoked (revisioned, idempotent, append-only audited).
Expired invitations are derived (`expired = true`), never silently reused.

### 2. Acceptance = self-enrollment (runtime plane, public)

`POST /v1/account-invitations:enroll` is unauthenticated. The invitee presents the
token plus the login handle and password **they** choose; the existing native
password policy and Argon2id verifier apply. In one transaction PostgreSQL locks
the invitation by digest, rejects unknown/expired/revoked/accepted tokens with one
indistinguishable outcome, revalidates that the issuing platform Principal is
still active and still holds `organization.provision`, creates the native identity
and password credential in the configured native authority, marks the invitation
accepted and creates the account entitlement. A login handle that already exists
is reported only to a valid token holder (the public native enrollment already
discloses that fact). The path is classified as an authentication attempt by the
shared HTTP admission budget (rate limit and bounded concurrency), and the token
has 256 bits of entropy, so guessing is infeasible. No administrator ever chooses
the owner's password.

### 3. Account entitlement — not tenant authority, not platform authority

An accepted invitation creates exactly one `account_entitlements` row for the
native identity: entitlement key `account.organization.create`, its limit, a
counter of organizations created, status and revision, the granting platform
Principal and the source invitation. It is **not** a `principal_authority_grants`
row: there is no Principal to hold it (a tenant Principal exists only inside an
Organization and a platform Principal would wrongly place the owner on the platform
plane). It is not registered in the tenant capability registry, it never appears in
`ActorContext` or `PlatformActorContext`, and possessing it confers no ability to
read or mutate any tenant or platform resource.

`ActorContext` does not obtain it. Pre-tenant operations already run on an
`AuthenticatedHttpSubject` (native session evidence) — the same boundary as
`self_organization_list` and `staff_invitation_accept`. The entitlement is resolved
inside PostgreSQL from the native identity and the **current native session id**,
which the database revalidates (active, unexpired, current session epoch, not
recovery-derived, not recovery-restricted, active authenticator).

### 4. Self-service business creation (runtime plane)

`POST /v1/me/organizations` (`self_organization_create`) lets an entitled native
HUMAN create a business they control. One transaction:

```text
READ     topology share gate; native session/identity revalidation (FOR SHARE)
LOCK     account_entitlements row FOR UPDATE   <- serialization root for the limit
VALIDATE idempotency (entitlement, key digest) -> replay or 409 on changed intent;
         entitlement active; organizations_created < max_organizations;
         policy key = newest immutable initial controller policy;
         credentialed native identity (request_auth.lock_credentialed_native_identity)
WRITE    Organization (+ default timezone/locale/currency), organization Party and
         first party revision, tenant HUMAN Principal 'native:<identity>', active
         identity binding, root control grants/representations, provisioning facts
         and the root fact (whose triggers seed the initial controller policy
         grants, the root staff membership and staff.read exactly as for
         platform-created roots); counter + 1; creation fact
EMIT     append-only account_organization_creations fact (audit with the creating
         identity); no outbox event — platform root provisioning emits none either
```

The root fact's `provisioned_by_principal_id` is the platform Principal that issued
the invitation: that is the authority the organization creation derives from, and
the existing `guard_authority_reference_tenant` invariant (root provenance must be a
platform Principal) remains unchanged. The creating identity is recorded in the
creation fact and in the root provenance reference
(`self-service-v1:<intent digest>:entitlement:<id>`). The issuing platform Principal
does not become tenant staff; the creating human becomes the root controller with
the current initial controller policy (`tenant-controller-v10`).

Inputs: `display_name` (required), optional `organization_key` (otherwise derived
from the display name plus a deterministic suffix), `timezone` (IANA, default
`America/Santo_Domingo`), `locale` (default `es-DO`), `currency` (ISO 4217, default
`DOP`). The `Idempotency-Key` header is required; identifiers are derived from the
identity and key digest, so a replay returns the original receipt and a changed body
returns `409`. The limit is enforced under the entitlement row lock and backstopped
by `CHECK (organizations_created <= max_organizations)` and
`UNIQUE (entitlement_id, sequence)`.

### 5. What is deliberately not done

* No entitlement suspension/revocation endpoint in this change. The existing
  `platform.identity.disable` kill switch disables the identity globally, which
  makes creation fail; a dedicated entitlement lifecycle is pending.
* No acceptance of an account invitation by an already enrolled identity (session +
  token); acceptance always enrolls a new native identity.
* The optional "platform creates the business and invites its first owner" variant
  is not implemented; issuing an account invitation with `max_organizations = 1`
  covers the product flow without an administrator-chosen password.
* No agent-tool projection: these are human credential and secret-possession
  operations.

## Consequences

* Platform authority never becomes tenant authority: issuing an invitation grants
  the issuer nothing inside the future tenant, and root grants are seeded only for
  the creating human. Tenant authority never becomes platform authority: the owner
  has no platform Principal, and the entitlement is consulted only by the
  self-service creation function.
* Revoking the issuer's `organization.provision` makes that issuer's pending
  invitations unusable (revalidated at acceptance). Already accepted entitlements
  remain, exactly like grants previously delegated by a later-revoked administrator.
* New database surfaces: four private tables (FORCE RLS without policies, no runtime
  table privileges), three control-plane functions, one platform-read function and
  three runtime `request_auth` functions owned by `request_platform_control_definer`.
  The runtime role gains exactly the three reviewed `request_auth` executions.
* Email delivery is at-most-once and synchronous; a crash between commit and send
  leaves a visible `pending` delivery status that the administrator resolves by
  revoking and reissuing.

## Rejected alternatives

* **Platform Principal per owner** — would put a paying customer on the platform
  plane and into every platform actor resolution path.
* **A new `AuthorityPlane.ACCOUNT` capability grant** — `principal_authority_grants`
  requires a Principal, and widening the plane vocabulary would ripple through every
  plane check without adding protection over a dedicated, narrow entitlement row.
* **New `platform.account_invitation.*` capabilities** — no existing Platform Owner
  would hold them without a grant backfill, and they would express the same authority
  as `organization.provision`.
* **Reusing the staff-invitation secret store and Communications worker** — the
  invitation has no Organization, so a tenant-scoped delivery intent would be a
  fabricated tenant relationship.
* **Short numeric WhatsApp codes** — would require per-invitation attempt counters
  and lockout state; a 256-bit token shared as a link or pasted code is
  guessing-resistant without new mutable public state.
