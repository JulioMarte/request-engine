# Tenant identity, authentication, and staff trust-root plan

Status: **normative implementation handoff / architecture contract**.

Branch: `cohesion/system-optimization`

This file intentionally keeps its historical path so existing references do not break, but its scope is broader than "identity-provider integration". The target is the **tenant identity and staff trust root** of Request Engine.

The architecture MUST make Request Engine fully operable with **zero external identity providers configured**, while allowing OIDC, WorkOS, Clerk, Descope, Entra ID, Keycloak, Auth0, or future providers to be added later without redesigning Tenancy, Principal, Representation, capability grants, or business modules.

---

## 0. Immediate repository state and first instruction

The implementation agent MUST begin from the exact current branch state, inspect current CI, and restore exact-head green evidence before layering identity work.

The previous handoff recorded a formatting-only Python failure from run `#4285` / `34156734648` at an earlier HEAD. That historical run is evidence only for that earlier commit; do not assume it still describes the current HEAD. Re-check exact-head CI first.

Before DDL or identity integration code, inventory the current implementation of:

```text
Organization
Principal
Party
Representation
capability grants / effective capabilities
operational authority snapshots/revisions
ActorResolver / ActorContext or current equivalent
idempotency
outbox
provider-event handling
RLS / tenant context
```

Do not create speculative parallel models until this audit is complete.

---

## 1. Product requirement

Request Engine cannot claim real tenant onboarding while creation of the first trusted human, staff membership, authentication, authority delegation, revocation, and recovery require SQL fixtures or an external SaaS identity provider.

The minimum providerless journey MUST be possible from a fresh PostgreSQL database:

```text
Request Engine starts with no external IdP configuration
        ↓
first human establishes a native authenticated identity
        ↓
platform/bootstrap trust admits one tenant-provisioning operation
        ↓
Request Engine Organization exists
        ↓
Organization Party exists
        ↓
Request Engine Principal exists
        ↓
Native identity is bound to that Principal
        ↓
first active staff membership/Representation exists
        ↓
minimum tenant-control and operational authority is materialized
        ↓
Organization becomes administratively operable
        ↓
first admin can invite/add a second staff member
        ↓
second staff member authenticates natively
        ↓
second staff member receives constrained RE authority
        ↓
second staff member can execute allowed business operations
        ↓
first admin revokes/suspends the second staff member
        ↓
existing session immediately loses RE authority
```

Only after this journey is proven should an external provider be treated as an implementation target.

---

## 2. Non-negotiable architecture rule

**Authentication establishes who presented a trusted identity. Request Engine establishes what that identity may do inside a tenant.**

The authentication authority may be:

```text
Request Engine Native
Generic OIDC
WorkOS
Clerk
Descope
future provider
```

External providers are optional adapters. They are not a prerequisite for Request Engine to function.

Request Engine remains authoritative for:

- `Organization` as the business tenant boundary;
- `Principal` as the internal execution/security identity;
- tenant membership state;
- `Party` as business/subject identity;
- `Representation` as delegated business authority;
- capability grants and delegation ceilings;
- operational scopes;
- authority revision/provenance;
- immediate business-authorization revocation;
- tenant isolation and foreign-row opacity;
- the mapping between authenticated identities and RE Principals.

No provider role or claim may directly become RE business authority.

Forbidden:

```text
provider says admin
        ↓
Request Engine grants *
```

Forbidden:

```text
provider membership appears
        ↓
automatic booking/catalog/queue/staff authority
```

Allowed only through an explicit RE-owned mapping/provisioning policy:

```text
external fact
        ↓
validated policy input
        ↓
RE-owned provisioning/authority command
        ↓
materialized RE authority
```

---

## 3. Core semantic separation

The implementation MUST keep these concepts distinct:

```text
Authentication identity  = who proved control of a credential/session
Principal                = internal RE security actor
Tenant membership         = where the Principal belongs administratively
Representation            = whom/what the Principal is allowed to act for
Capability                = what action the Principal may perform
Scope                     = where/on what that action may be performed
```

A useful invariant is:

```text
Authentication proves WHO.
Membership establishes WHERE the actor belongs.
Representation establishes WHOM/WHAT the actor may act for.
Capabilities establish WHAT the actor may do.
Scope constrains WHERE/ON WHAT it may be done.
```

None of those facts may silently imply the next.

In particular:

```text
valid credential != active membership
active membership != administrative authority
provider role != RE capability
invitation != authority
same email != same Principal
```

---

## 4. Target topology

```text
                    Authentication Authorities
                              |
          +-------------------+-------------------+
          |                   |                   |
       RE Native          Generic OIDC        B2B providers
                                                  |
                                      WorkOS / Clerk / Descope
          |                   |                   |
          +-------------------+-------------------+
                              |
                              v
                    AuthenticatedSubject
                              |
                              v
                       IdentityBinding
                              |
                              v
                          Principal
                              |
                +-------------+-------------+
                |                           |
                v                           v
        Human staff membership        Service/integration
                |
                v
          Representation
                |
                v
        Capability grants
                |
                v
        Effective authority
                |
                v
   Booking / Queue / Catalog / Parties / ...
```

`AuthenticatedSubject` is provider-neutral. `IdentityBinding` is RE-owned correlation. `Principal` and all business authorization remain independent of the authentication mechanism.

---

## 5. IdentityAuthority

Introduce a provider-neutral concept representing a source capable of asserting authenticated subjects.

Conceptual fields, subject to the Slice 1 schema audit:

```text
identity_authority_id
kind                     -- native | oidc | workos | clerk | descope | ...
issuer_or_environment    -- stable namespace, never a secret
status
configuration_ref        -- optional secret/config indirection, never raw secret
created_at
revision
```

Do not hard-code one `provider` column on Organization as if a tenant could only ever authenticate through one authority.

An Organization MAY eventually have multiple configured authorities concurrently.

Examples:

```text
Clinic A
  - RE Native
  - WorkOS production connection

Clinic B
  - RE Native only

Enterprise C
  - corporate OIDC only
```

The data model should permit coexistence even if the first UI only exposes Native.

---

## 6. IdentityBinding

Replace the conceptual `ExternalIdentityBinding` with provider-independent `IdentityBinding`.

A binding means only:

> this authenticated subject is correlated to this RE Principal in this valid tenant/security context.

It does **not** itself grant business authority.

Conceptual fields:

```text
organization_id             -- if binding is tenant-scoped after audit decision
principal_id
identity_authority_id
subject_id                  -- immutable/stable identifier within that authority namespace
status                      -- pending | active | suspended | revoked
last_seen_at
created_at
revoked_at
revision

-- optional external correlation metadata, not canonical authority
external_organization_id
external_membership_id
```

The stable identity key is conceptually:

```text
(identity_authority_id, subject_id)
```

possibly plus the tenant boundary depending on the resolved Principal model.

Email, phone number, display name, provider role, and provider organization name are never identity keys.

---

## 7. Native identity and credential boundary

`RE Native` is the first real authentication implementation, not merely a fake adapter.

Native authentication MUST be designed behind the same provider-neutral authentication boundary used by later adapters.

Native credentials MUST NOT be stored on:

```text
Principal
Party
StaffMembership
Representation
```

Keep credential/session concerns in a narrowly scoped security/identity subsystem at the platform edge or another ownership location justified by the Slice 1 audit.

Minimum first-party native lifecycle required for providerless operation:

```text
native identity creation
credential enrollment
login/authentication
session or token issuance
logout
session invalidation
credential reset/recovery
credential disable/revoke
```

Do not attempt to build every identity-provider feature in the first slice. Social login, enterprise SSO, passkeys, sophisticated MFA, device management, and other conveniences can follow after the minimal trust root is secure.

Credential material MUST use accepted password/secret hashing primitives and deployment-managed secrets; raw passwords, reset secrets, access tokens, refresh tokens, or equivalent sensitive material must never enter audit logs, telemetry, outbox payloads, or ordinary domain tables.

Native authentication owns native credential validity. Tenancy still owns business authority.

---

## 8. One Principal may have multiple authentication bindings

The design SHOULD permit one RE Principal to be reachable through multiple authenticated identities where explicitly linked.

Example migration:

```text
Principal P1
  ├─ Native binding N1
  └─ WorkOS binding W1

Membership M1
Representation R1
Grants G1
```

After WorkOS is proven and accepted:

```text
disable N1
```

while preserving:

```text
Principal P1
Membership M1
Representation R1
Grants G1
Audit history
```

Changing authentication provider must not require reconstructing business authority.

This is a required portability property.

---

## 9. Account linking is a security boundary

Never automatically merge/link identities because they share:

```text
email
phone
name
domain
provider metadata
```

Default:

```text
same email across two IdentityAuthorities
        !=
permission to link the identities
```

A future/public account-link operation must require a strong proof such as:

- successful authentication to both identities; or
- an explicitly authorized recovery/admin workflow with auditable anti-takeover policy.

The first implementation MAY simply disallow public cross-authority linking and expose only a tightly controlled reconciliation path.

Required invariant:

```text
no implicit cross-authority account linking
```

---

## 10. Staff membership and Representation

Before adding a new membership table, inspect whether the existing Representation model plus existing Principal metadata can correctly express staff membership lifecycle.

Do not create a parallel authorization system merely because external providers use the word "membership".

The system must nevertheless be able to answer, owner-backed and unambiguously:

```text
Is this human active staff of this Organization?
What Principal represents them?
What business Party/authority anchor do they represent?
What capabilities/scopes are effective?
What may they delegate?
Who created/changed/revoked this authority?
What revision produced the current state?
```

Required conceptual staff lifecycle:

```text
INVITED / PENDING
ACTIVE
SUSPENDED
REVOKED
```

Suspension/revocation must affect RE authorization even if a native or external authentication session remains otherwise cryptographically valid.

---

## 11. Human and non-human Principals

Do not force bots, integrations, automation workers, or platform actors into a human `StaffMembership` concept solely because all execute as Principals.

Preserve or refine the existing Principal-kind taxonomy after audit, conceptually distinguishing at least:

```text
human/operator
service/bot
integration
platform/deployment
```

The staff lifecycle in this plan is for human/operator membership. Service and integration Principal lifecycle must remain compatible with the same authorization infrastructure without pretending they are employees.

---

## 12. Tenant context is independent of authentication identity

A person may belong to multiple Organizations.

Therefore:

```text
authenticated identity != selected tenant
```

A protected request must resolve an unambiguous:

```text
authenticated subject
        ↓
Principal
        +
Organization context
```

before business authorization.

Never silently select a tenant using:

```text
first membership
most recent membership
email domain
provider default organization
arbitrary provider claim
```

If tenant context is absent or ambiguous, return a typed failure rather than guessing.

Provider organization/tenant context may participate in exact correlation, but it is never sufficient by itself to create RE authority.

---

## 13. Authentication adapter contracts: use capability facets, not one giant provider port

Do **not** create a monolithic interface such as:

```python
class IdentityProviderPort(Protocol):
    verify(...)
    ensure_organization(...)
    ensure_membership(...)
    invite_member(...)
    revoke_membership(...)
    webhooks(...)
```

That interface accidentally assumes every authentication provider is a B2B directory. Generic OIDC does not guarantee organization creation, invitations, membership APIs, or webhooks.

Use narrow provider-neutral facets, naming subject to repository conventions:

```text
Authenticator
  verify/assert authenticated subject

IdentityDirectory             optional
  lookup/provision external identities

ExternalOrganizationDirectory optional
  ensure/read provider-side organizations

ExternalMembershipDirectory   optional
  ensure/read/revoke provider-side memberships

InvitationTransport           optional
  deliver/revoke provider invitations

IdentityEventSource            optional
  verify/normalize webhook or event ingress
```

Illustrative capability matrix:

| Adapter | Authenticate | Identity directory | External org | External membership | Invitation transport | Events |
|---|---:|---:|---:|---:|---:|---:|
| RE Native | yes | yes | n/a | n/a | optional | internal |
| Generic OIDC | yes | usually no | no | no | no | optional |
| WorkOS | yes | yes | yes | yes | yes | yes |
| Clerk | yes | yes | yes | yes | yes | yes |
| Descope | yes | yes | tenant-specific | tenant-specific | provider-specific | yes |

Tenancy/application code must import provider-neutral contracts only. Vendor SDK types remain at adapter edges.

---

## 14. Authentication resolution contract

Preserve the current HTTP actor boundary (`ActorResolver` / `ActorContext` or exact current equivalent) rather than spreading auth logic through business routers.

Provider-neutral resolution should conceptually perform:

```text
receive credential/session assertion
        ↓
select configured Authentication Authority deterministically
        ↓
verify credential/assertion according to that authority
        ↓
obtain AuthenticatedSubject(authority_id, subject_id, metadata)
        ↓
resolve active IdentityBinding
        ↓
resolve exact Organization context
        ↓
load current Principal + current RE authority
        ↓
return ActorContext
```

Never accept the following as authoritative from an ordinary request body:

```text
organization_id
principal_id
capabilities
delegation ceiling
Representation scopes
```

If authentication succeeds but no active binding/membership exists, return a typed provisioning/unbound state. Never synthesize an unrestricted Principal.

---

## 15. Authorization revision / immediate revocation

Business authority cannot be trusted solely from a long-lived token snapshot.

Introduce or reuse a monotonic authority revision/epoch mechanism if the current design does not already provide equivalent guarantees.

Conceptually:

```text
Principal / tenant authority revision = 41
session/cache was resolved at revision = 40
        ↓
re-resolve or reject stale authority
```

Any operation that changes effective authority should invalidate stale authorization state, including:

```text
membership suspend
membership revoke
binding revoke
authority replacement
delegation change
relevant Representation revocation
```

The exact mechanism may be a revision, epoch, authoritative DB read, bounded cache keyed by revision, or an existing repository mechanism. The invariant matters more than the implementation name:

> after an RE authority revocation commits, a previously valid external or native session must not continue authorizing protected business commands.

For RE Native, where RE controls both authorization and sessions, revocation SHOULD also invalidate affected native sessions where policy requires it.

---

## 16. Bootstrap: zero-to-one trust root

The current `organization.bootstrap` path only establishes root operational authority after prerequisite objects already exist. It does not solve zero-to-one tenant creation.

Introduce a **platform/deployment provisioning authority** distinct from ordinary tenant authority.

It may admit a narrow command such as conceptually:

```text
tenancy.provision_organization
```

It must not receive normal tenant business capabilities merely because it can bootstrap a tenant.

### 16.1 Bootstrap authority should be narrow and consumable

Prefer one-time or tightly bounded provisioning intents over a permanently omnipotent bootstrap credential.

Conceptual:

```text
ProvisioningIntent
  id
  nonce/dedupe key
  permitted_action = organization.provision
  expires_at
  consumed_at
  provenance
```

The trust-root creation must be idempotent and concurrency-safe.

### 16.2 Atomic internal bootstrap

Where compatible with the audited schema, one internal PostgreSQL transaction should create/reconcile:

1. Organization;
2. organization Party;
3. first Principal;
4. Native or other IdentityBinding;
5. first active staff membership/Representation;
6. minimum tenant-control capability grants;
7. required root operational Representation scopes;
8. audit/provenance;
9. provisioning state and any durable outbox intent.

Either the internal trust root becomes visible coherently or none of it does.

No external network call may occur while holding this transaction open.

---

## 17. Tenant-control safety: do not define the invariant as "last admin"

Core authorization should not depend on a hard-coded `admin` role.

The real invariant is:

> an ordinary tenant-level authority change must not strand the tenant with zero active Principals able to perform the minimum tenant-control/recovery operations, unless an explicit platform recovery path is being used.

Define the exact minimum control authority from effective capabilities/policy after the schema audit.

This invariant must be concurrency-safe.

The following race must not strand the tenant:

```text
Controller A revokes Controller B
Controller B revokes Controller A
```

Application pre-checks alone are insufficient if concurrent transactions can violate the invariant. PostgreSQL proof is required.

---

## 18. Delegation and grant ceiling

Possession is not delegation authority.

Required invariant:

```text
has capability X
    !=
may delegate capability X
```

The effective authority delegated by one Principal must be a subset of the grantor's explicitly delegable authority under current policy:

```text
delegated_authority ⊆ grantor_delegable_authority
```

And delegation must never expand through chains:

```text
Authority(C)
  ⊆ B's delegable ceiling
  ⊆ A's delegable ceiling
```

A Principal must not self-escalate by granting itself new capabilities/scopes or by routing through another membership/Representation.

The implementation must validate both capability and scope ceilings, not just capability names.

---

## 19. Declarative authority replacement with optimistic concurrency

Prefer a constrained declarative command such as:

```text
staff_authority_replace
```

over a public `grant arbitrary capability` primitive.

Authority replacement MUST support revision conflict detection.

Conceptually:

```text
staff_authority_replace(
    membership_id,
    expected_revision,
    desired_authority
)
```

If the current revision differs:

```text
AuthorityRevisionConflict
```

Do not silently apply last-write-wins to security authority administration.

---

## 20. Policy bundles are convenience, not core roles

Do not create core capabilities such as:

```text
role.admin
role.receptionist
role.doctor
```

Use semantic capabilities and optional versioned policy bundles.

Example:

```text
Receptionist bundle revision 3
  -> booking operational permissions
  -> queue permissions
  -> allowed patient lookup/register permissions
  -> no staff administration
  -> no protected commercial/configuration authority unless explicitly added
```

When a bundle is materialized into authority, preserve provenance such as:

```text
assigned_from_bundle_id
assigned_from_bundle_revision
assigned_by
assigned_at
```

Runtime authorization should continue to evaluate materialized RE authority, not a provider role string or mutable bundle name.

---

## 21. Staff administration surface

Final operation names must follow the repository's canonical operation naming rules, but the semantic surface must cover at least:

### Queries

```text
staff_membership_list
staff_membership_read
staff_effective_authority_read
staff_invitation_list
identity_binding_read
identity_authority_list/read as justified
```

### Commands

```text
organization_provision
staff_invitation_create
staff_invitation_revoke
staff_membership_activate
staff_membership_suspend
staff_membership_reactivate
staff_membership_revoke
staff_authority_replace
identity_binding_reconcile
identity_binding_revoke
```

Native identity lifecycle operations belong to the authentication/identity owner, not arbitrary Tenancy tables.

Suggested management capabilities remain semantic:

```text
organization.provision            -- platform/deployment only
staff.read
staff.invite
staff.manage_membership
staff.manage_authority
identity.bind
identity.reconcile
```

Do not expose `organization.provision` as a normal public/patient/agent operation.

---

## 22. Invitation lifecycle is RE-owned; delivery is replaceable

Invitation intent belongs to Request Engine. Delivery may be native or external.

Provider-independent flow:

```text
admin creates StaffInvitation intent
        ↓
RE commits durable invitation state
        ↓
InvitationTransport
   ├─ native email/WhatsApp/link delivery
   ├─ WorkOS
   ├─ Clerk
   └─ other
        ↓
recipient authenticates
        ↓
recipient proves/claims invitation according to policy
        ↓
IdentityBinding correlated or created
        ↓
RE membership/Representation activated
        ↓
RE capabilities become effective
```

A pending invitation grants zero business authority.

External invitation IDs/URLs are correlation/delivery metadata, not canonical RE authority.

Invitation acceptance must be idempotent and must activate at most the intended membership.

---

## 23. Provider-first facts must not silently create authority

When an external provider reports a new user/org/membership that RE did not request, the safe default is:

```text
external membership observed
        ↓
record/reconcile external fact
        ↓
PENDING / UNCLAIMED / RECONCILIATION_REQUIRED
        ↓
NO RE BUSINESS AUTHORITY
```

Activation may occur only when justified by an RE-owned fact or policy, for example:

```text
matching active StaffInvitation intent
explicit tenant provisioning policy
authorized tenant-control command
platform recovery/provisioning workflow
```

This protects against provider-side role/membership compromise becoming RE authority by implication.

---

## 24. External-provider I/O is a saga, never a distributed transaction

For providers that support organization/membership provisioning, do not hold PostgreSQL locks while making network calls.

Pattern:

```text
RE transaction
        ↓
outbox
        ↓
provider worker
        ↓
external API
        ↓
RE reconciliation transaction
```

Do not use one giant state machine for all identity concerns.

Separate at least conceptually:

```text
organization provisioning state
identity binding state
staff membership state
invitation state
external synchronization/reconciliation state
```

This permits valid combinations such as:

```text
membership = ACTIVE
native binding = ACTIVE
workos sync = RECONCILIATION_REQUIRED
```

without incorrectly disabling a staff member who can still authenticate natively.

---

## 25. Provider events and reconciliation

Use a provider-neutral ingress boundary with provider-specific signature verification.

Flow:

```text
HTTP/provider event
  -> verify authenticity/signature
  -> validate timestamp/replay window where applicable
  -> deserialize provider payload
  -> normalize to provider-neutral event/fact
  -> persist dedupe identity
  -> decide whether event is authoritative or only a reconciliation signal
  -> reconcile through owner command
  -> record provenance/result
```

Never pass raw vendor payloads into Tenancy domain commands.

Webhook delivery is at-least-once. Replay must be harmless.

Out-of-order protection must be provider-aware:

- use monotonic provider version/order metadata when trustworthy;
- otherwise treat the webhook as a **dirty/reconciliation signal** and fetch/derive current provider state;
- never allow an older event to resurrect revoked RE authority.

External events may influence correlation state but cannot bypass RE provisioning/delegation policy.

---

## 26. Source-of-truth matrix

| Fact | Authority |
|---|---|
| Native credential validity | RE identity/authentication subsystem |
| Native session validity | RE identity/authentication subsystem |
| External password/passkey/MFA/session | configured external Authentication Authority |
| External provider user/subject ID | external provider |
| Authenticated subject namespace | corresponding Authentication Authority |
| Identity → Principal correlation | Request Engine `IdentityBinding` |
| RE Organization ID | Request Engine |
| RE Principal ID | Request Engine |
| staff membership state | Request Engine |
| Organization business Party | Request Engine |
| Representation / operational authority | Request Engine |
| RE capabilities/delegation ceiling | Request Engine |
| policy bundles | Request Engine |
| provider role | external metadata / explicit mapping input only |
| provider org/membership correlation | RE binding/sync metadata + provider fact |
| invitation intent | Request Engine |
| invitation delivery state | delivery provider + reconciled RE intent |
| effective authorization to a business command | Request Engine |

---

## 27. Failure semantics

Use typed failures. Avoid generic authorization/provisioning 500s.

Examples, final naming subject to repository conventions:

```text
AuthenticationRequired
AuthenticationAuthorityUnavailable
CredentialInvalid
IdentityNotBound
IdentityBindingSuspended
IdentityBindingRevoked
TenantContextRequired
TenantContextAmbiguous
PrincipalProvisioningRequired
OrganizationAlreadyProvisioned
ProvisioningIntentExpired
ProvisioningIntentConsumed
MembershipAlreadyActive
MembershipSuspended
MembershipRevoked
TenantControlAuthorityWouldBeStranded
GrantNotDelegable
AuthorityRevisionConflict
IdentityLinkProofRequired
IdentityLinkConflict
ProviderEventReplay
ProviderReconciliationRequired
ProviderUnavailable
```

Provider unavailability must not roll back already committed internal state when a durable saga is in use.

---

## 28. Observability and secrecy

Emit structured correlation-friendly telemetry such as:

```text
identity_authority_kind
identity_authority_id
organization_id
principal_id
provisioning_id
membership_id
binding_id
authority_revision
provider_event_type
provider_event_id/hash where safe
state transition
attempt
result
correlation_id
```

Never log or place in ordinary audit/outbox telemetry:

```text
passwords
password hashes
access tokens
refresh tokens
reset secrets
MFA secrets
recovery codes
raw webhook signatures
API secrets
sensitive JWT claims
```

Audit business/security decisions and provenance, not reusable credentials.

---

## 29. Database sequence

Do not start with a giant migration.

### P0 — current-schema audit

Inspect exact current tables/functions/RLS for:

```text
organizations
principals
parties
representations
capability grants
authority revisions/snapshots
idempotency
audit
outbox
actor/tenant context
staff administrative contacts
```

Deliver a disposition:

```text
reuse as-is
extend
replace only with evidence
missing
```

Resolve explicitly whether Principal is tenant-scoped and where a reusable authentication identity may safely live without weakening RLS.

### P1 — minimal native identity/binding schema

Add only what the audit proves is missing for:

```text
IdentityAuthority
Native identity/credential lifecycle
IdentityBinding
session/revocation lifecycle
authority revision link if needed
```

### P2 — zero-to-one provisioning

Add the minimum structures/functions needed to create the trust root atomically and idempotently.

### P3 — staff lifecycle

Add only missing lifecycle/provenance/revision state. Reuse Representation/grant infrastructure whenever semantically correct.

### P4 — external synchronization

Add provider correlation/event dedupe/reconciliation state only when implementing the first external adapter.

### P5 — RLS/indexes/constraints

Every new tenant-owned relation must preserve tenant opacity.

Consider constraints for:

```text
(identity_authority_id, subject_id) uniqueness in resolved scope
binding uniqueness
provider membership correlation
provider event dedupe
one active membership/binding rules where required
revision consistency
native credential uniqueness in its correct namespace
```

Exact constraints must follow the audited global-vs-tenant identity model.

---

## 30. Security invariants that block completion

The feature is incomplete unless all are demonstrated:

1. **Providerless operability** — RE works with no external IdP configured.
2. **No implicit authority** — authentication, provider membership, provider role, and invitation never directly grant business authority.
3. **No self-escalation** — a Principal cannot expand its own authority.
4. **Grant ceiling** — delegation is bounded by explicit delegable capability + scope policy.
5. **Tenant-control continuity** — ordinary concurrent revocation cannot strand all tenant-control authority.
6. **Cross-tenant opacity** — foreign bindings/memberships/invitations remain opaque.
7. **Immediate RE revocation** — valid sessions cannot preserve revoked business authority.
8. **Native session revocation** — where RE controls sessions, security-state changes invalidate them according to policy.
9. **No implicit identity linking** — matching email/phone/name never merges Principals.
10. **Account-link takeover resistance** — any supported link operation requires explicit strong proof/policy.
11. **Webhook replay safety** — duplicate delivery is harmless.
12. **Out-of-order protection** — stale provider events cannot resurrect authority.
13. **Provider compromise containment** — provider roles/memberships remain constrained inputs.
14. **Optimistic authority concurrency** — stale authority replacement fails explicitly.
15. **Bootstrap containment** — provisioning authority cannot become ordinary tenant superuser authority by implication.
16. **Credential secrecy** — credential material never leaks into domain/audit/telemetry surfaces.

---

## 31. Test and proof plan

### Unit/domain

Prove:

```text
identity namespace rules
binding lifecycle
no email-based auto-link
membership lifecycle
grant ceiling
scope ceiling
no self-escalation
policy-bundle provenance
authority revision conflicts
provider role mapping cannot emit unknown/non-grantable capabilities
```

### Authentication integration

Prove:

```text
native login -> AuthenticatedSubject -> correct Principal
wrong credential rejected
revoked native credential/session rejected
valid external subject with no binding remains unauthorized
wrong/ambiguous tenant context rejected
multiple bindings resolve only by exact authority+subject+tenant rules
```

### PostgreSQL

Prove:

```text
atomic Organization + Party + first Principal + binding + root authority bootstrap
concurrent duplicate provisioning creates one trust root
RLS/foreign-row opacity for every new tenant-owned relation
concurrent invitation acceptance is idempotent
revoke races cannot resurrect authority
concurrent tenant-controller revocation cannot strand authority
stale staff_authority_replace gets AuthorityRevisionConflict
provider event replay is harmless
out-of-order provider facts are ignored/reconciled safely
audit/provenance commits atomically with authority changes
```

### Architecture fitness tests

Prove:

```text
Tenancy domain/application imports no WorkOS/Clerk/Descope SDK types
business modules import no credential implementation details
Native adapter satisfies the same Authenticator contract used by external adapters
adding/removing an external adapter requires no business-domain schema redesign
```

---

## 32. Required E2E proofs

### E2E A — providerless first principle

Run from fresh PostgreSQL with external provider configuration absent and network access to identity SaaS unavailable:

```text
1. create native human identity
2. authenticate natively
3. provision Organization
4. establish first Principal + membership + root authority
5. configure Organization/Location/Offering/Resource/Queue/communications through supported APIs
6. invite/create second staff identity
7. second staff authenticates natively
8. activate constrained membership/authority
9. second staff performs allowed Queue/Booking operations
10. second staff is denied staff-authority/configuration operations
11. first staff revokes/suspends second staff
12. second staff's existing session immediately loses RE business authority
```

This proof is mandatory before an external provider is considered necessary for product operation.

### E2E B — Native → external provider migration

Given:

```text
Principal P1
NativeBinding N1
Membership M1
Representations/Grants G1
```

Add an external binding:

```text
WorkOS/OIDC Binding W1 -> P1
```

Then disable N1.

Prove unchanged:

```text
Principal P1
Membership M1
Representations/Grants G1
business audit history
```

No authority recreation is allowed.

### E2E C — simultaneous authentication authorities

Where supported by product policy, prove two explicitly linked authentication methods resolve to the same Principal and exactly the same current RE authority.

### E2E D — external provider removal

Disable/remove the external adapter/configuration and prove Native-based:

```text
Tenancy
staff administration
Booking
Queue
Catalog
Parties
```

continue functioning without domain/schema rollback.

---

## 33. Implementation slices

Work in narrow, certifiable slices.

### Slice 0 — exact-head truth

- inspect current branch/HEAD and CI;
- restore green exact-head Python/architecture evidence;
- do not inherit stale CI claims from the earlier handoff.

### Slice 1 — authority/authentication schema audit

Deliver:

- exact current tables/functions/RLS;
- current Principal provisioning path;
- current Representation/grant semantics;
- current ActorResolver/ActorContext path;
- current authority revision/revocation semantics;
- decision on tenant-scoped Principal vs reusable authentication identity;
- disposition of existing structures before DDL.

### Slice 2 — provider-neutral authentication contracts

Implement:

```text
IdentityAuthority
AuthenticatedSubject
IdentityBinding contracts
Authenticator facet
optional provider capability facets
fake fixtures for deterministic tests
architecture rules against vendor leakage
```

### Slice 3 — RE Native authentication

Implement the minimum secure native identity/credential/session lifecycle necessary for first-party operation.

No external SDK required.

### Slice 4 — providerless zero-to-one tenant bootstrap

Implement the owner command/internal transaction that creates/reconciles:

```text
Organization
business Party
first Principal
Native IdentityBinding
first membership/Representation
bootstrap tenant-control capabilities
operational authority scopes
audit/provenance
```

Protect it with narrow platform/bootstrap trust and idempotency.

### Slice 5 — providerless staff lifecycle

Implement:

```text
invitation intent
list/read staff
activate/suspend/reactivate/revoke
authority replace with expected revision
grant/scope ceiling
no self-escalation
tenant-control continuity
immediate RE revocation
native session invalidation policy
```

At this point E2E A must pass.

### Slice 6 — provider conformance layer

Finalize optional capability facets and conformance tests using Native + fake adapters. Do not add vendor schema concepts to Tenancy.

### Slice 7 — Generic OIDC authentication-only adapter

Prove an authenticator that may provide **no** organization/invitation/membership API can still bind a subject safely to RE.

This is a key proof that the abstraction is not secretly WorkOS/Clerk-shaped.

### Slice 8 — external event/reconciliation infrastructure

Implement provider-neutral dedupe/reconciliation using fake fixtures first.

### Slice 9 — first B2B provider

Implement WorkOS **or** Clerk end to end as an adapter.

External provider organizations/memberships remain correlations, not canonical RE authority.

### Slice 10 — portability/migration proof

Implement enough of a second external adapter or fixture to prove:

```text
no Principal redesign
no membership redesign
no Representation redesign
no capability redesign
no business-module redesign
```

Run E2E B/C/D as applicable.

### Slice 11 — onboarding and authorized operation catalog

Expose owner-backed readiness facts such as:

```text
identity
  native_or_external_authentication_ready
  initial_admin_active

staff_administration
  tenant_control_authority_ready
  staff_management_available
```

Onboarding reads readiness; it does not own provisioning.

Authorized operation discovery surfaces staff-management operations only when current RE capabilities allow them.

### Slice 12 — adversarial closure

Run all concurrency, tenant-opacity, account-linking, provider compromise, replay, stale-authority, providerless, and portability proofs.

Only after this slice may documentation claim the tenant/staff trust root is complete.

---

## 34. Definition of Done

Do not call this feature complete until **all** are true:

1. Request Engine is fully operable with **zero external identity providers configured**.
2. A fresh human can create/use a secure RE Native identity through supported surfaces.
3. A fresh authenticated human can become the first administrator/controller of a new tenant without SQL/manual fixtures.
4. Organization, business Party, Principal, IdentityBinding, membership, grants and required root authority are created atomically or through a documented recoverable internal/external saga where appropriate.
5. An administrator/controller can invite/add, inspect, modify, suspend/reactivate and revoke staff through owner-backed operations.
6. An employee cannot self-escalate or delegate beyond explicit capability/scope ceilings.
7. Ordinary authority changes cannot strand all tenant-control authority, including under concurrency.
8. Stale authority-replacement writes fail explicitly rather than silently overwriting newer changes.
9. Revoked/suspended staff lose RE business authorization immediately even when an authentication session remains cryptographically valid.
10. Native session/credential state is invalidated according to explicit security policy when relevant.
11. Foreign tenant staff/bindings/invitations/provider correlations are opaque.
12. Matching email/phone/name never causes implicit cross-authority account linking.
13. Invitation state never grants authority before valid activation.
14. Provider-first external membership never creates authority without an RE-owned provisioning intent/policy.
15. Webhook replay/out-of-order delivery cannot duplicate or resurrect authority.
16. Native authentication satisfies the same provider-neutral authentication contract used by external adapters.
17. Generic OIDC can authenticate/bind without requiring B2B organization/membership/invitation capabilities.
18. At least one real external provider can be added without altering canonical Principal/Membership/Representation/Capability semantics.
19. A second-provider or conformance proof demonstrates portability without schema/domain redesign.
20. Native → external-provider migration preserves the same Principal and business authority.
21. Removing an external provider does not break providerless Request Engine operation.
22. No vendor SDK types leak into Tenancy domain/application or business-module contracts.
23. Onboarding reports missing identity/admin prerequisites machine-readably.
24. Authorized operation discovery reflects current effective RE authority.
25. Credential secrets never leak through domain/audit/telemetry/outbox surfaces.
26. Current semantic guarantees and PostgreSQL current-product proof remain green on exact HEAD.

---

## 35. Things the implementation agent MUST NOT do

- Do not make WorkOS, Clerk, Descope, OIDC, or any external IdP mandatory for Request Engine startup or core business operation.
- Do not model Native as a privileged special case that bypasses the same authenticated-subject/binding boundary used by external adapters.
- Do not make provider organization or membership objects the canonical RE tenant/membership model.
- Do not equate email, phone, or display name with identity.
- Do not auto-link identities by matching contact attributes.
- Do not accept tenant/principal/capability/Representation authority from ordinary request bodies.
- Do not equate authentication success with staff membership.
- Do not equate staff membership with business authority.
- Do not grant `*` because a provider claim says `admin`.
- Do not introduce `admin`, `receptionist`, `doctor`, etc. as hard-coded core authorization roles.
- Do not expose unrestricted arbitrary-capability grant APIs where a constrained declarative authority operation will suffice.
- Do not use last-write-wins for authority replacement.
- Do not rely on application-only checks for concurrency-sensitive tenant-control continuity.
- Do not let provider-first membership events silently activate RE authority.
- Do not call external providers while holding PostgreSQL locks.
- Do not create one monolithic provider interface that all providers must fake unsupported B2B capabilities to implement.
- Do not create one giant state machine combining membership, identity binding, invitation, provisioning and provider synchronization.
- Do not let stale webhooks resurrect revoked authority.
- Do not store native credential material on Principal, Party, Representation or staff membership rows.
- Do not log tokens/passwords/reset secrets/webhook secrets.
- Do not create a second authorization/membership model if the existing Representation/grant model already owns the semantics correctly.
- Do not weaken RLS, provenance, idempotency, revocation or concurrency guarantees for provider convenience.
- Do not resume MCP/tool projection until the human identity/staff trust root is strong enough to determine who may discover and execute those operations.

---

## 36. First concrete instruction for the next agent

Start from exact branch truth, then perform Slice 1 before writing migrations.

The strategic objective is **not**:

> support WorkOS / Clerk / Descope.

It is:

> Make Request Engine capable of authenticating its own first human, provisioning a real tenant and its first trusted staff authority, administering human staff securely, and revoking that authority immediately without any external identity service; then make external authentication and B2B identity systems replaceable, optional adapters that can be added, migrated, combined, or removed without redesigning Request Engine's canonical business authority model.

The strongest architectural proof is therefore not merely "two provider adapters compile". It is:

```text
providerless RE works completely
        +
external provider can be added without authority redesign
        +
Principal/authority survive provider migration
        +
external provider can be removed without breaking the product
```

That is the trust root this branch must close before additional administrative UX or MCP/tool projection becomes the priority.
