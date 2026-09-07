# Identity provider and staff provisioning plan

Status: **handoff / implementation plan for the next agent**.

Branch: `cohesion/system-optimization`

Starting HEAD when this plan was written: `51b713510a84b008fb1e39447cdfff1291151c85`.

The branch is intentionally still in the system-optimization phase. Do not create a new branch unless the integration-lane rules require it. Continue on `cohesion/system-optimization` and keep the existing draft PR as the integration vehicle.

## 0. Immediate repository state

The current exact-head CI run `#4285` / `34156734648` failed in `Python quality and architecture` at `ruff format --diff`; Ruff lint already passed. PostgreSQL jobs were skipped because the aggregate fails closed when Python quality fails.

The formatter reported only mechanical formatting differences in:

- `src/request_engine/entrypoints/http/app.py`
- `src/request_engine/entrypoints/http/module_composition.py` (missing final newline)
- `src/request_engine/entrypoints/http/operational_app.py`
- `src/request_engine/modules/onboarding/api/router.py`

**First task for the next agent:** apply `uv run ruff format` equivalent changes, push, and obtain a green exact-head Python lane before layering provisioning work. Do not claim PostgreSQL evidence from run #4285; PostgreSQL did not execute.

## 1. Product problem to solve

Request Engine cannot honestly claim self-service tenant onboarding while the first trusted administrator, employee memberships, Representation/grant lifecycle, and external identity binding are incomplete.

A business tenant must be able to reach this state without SQL fixtures:

```text
external human identity exists
        ↓
Request Engine Organization exists
        ↓
Organization Party exists
        ↓
first human Principal is bound to the external identity
        ↓
that Principal has explicit membership/Representation authority
        ↓
that Principal receives the minimum bootstrap/admin capabilities
        ↓
Organization becomes administratively operable
        ↓
admin can invite/add/revoke later staff without SQL
```

The architecture must support identity platforms such as WorkOS AuthKit, Clerk, Descope, and future OIDC/JWT providers without making any of their tenant/organization/role models the Request Engine domain model.

## 2. Non-negotiable architecture rule

**External identity providers own authentication and credential lifecycle. Request Engine owns business tenancy and operational authorization.**

Provider responsibilities may include:

- user authentication;
- MFA/passkeys/passwords/social/SSO;
- provider sessions;
- provider user IDs;
- provider organization/tenant IDs when the deployment chooses to use them;
- provider membership/invitation lifecycle;
- provider webhooks/events;
- optional coarse provider roles used as input to a policy mapping.

Request Engine remains authoritative for:

- `Organization` as the tenant boundary;
- `Principal` as the authenticated execution identity inside RE;
- `Party` as business/subject identity;
- `Representation` as delegated business authority;
- capability grants/effective capabilities;
- operational scopes such as manage profile/supply/terms/discovery;
- revocation semantics that must immediately affect RE execution;
- provenance/audit of who granted/revoked authority;
- tenant isolation and foreign-row opacity.

Never authorize `booking.manage_supply`, `catalog.manage`, `queue.configure`, etc. merely because WorkOS/Clerk/Descope says `admin`. Provider roles can be translated by an explicit mapping policy into RE grants, but the effective RE authorization remains materialized and enforced by Tenancy/security.

## 3. Why the provider abstraction is necessary

WorkOS, Clerk and Descope all support B2B organization/tenant membership but differ materially:

- WorkOS models users and `OrganizationMembership` and supports users in zero, one or many organizations.
- Clerk models Organizations, memberships, creator/default roles and role sets.
- Descope models project-level identities plus tenant associations/tenant roles and can optionally isolate the same login ID per tenant.

Therefore no table or domain object should be named after a provider-specific resource such as `clerk_organization_membership` as the canonical model. Provider-specific identifiers belong in correlation/binding tables or adapter state.

## 4. Target conceptual model

Before writing migrations, audit the existing schema and reuse current `Organization`, `Principal`, `Party`, `Representation` and grant structures wherever their semantics are sound. Do not duplicate them merely to match this plan.

The target concepts are:

### 4.1 ExternalIdentityBinding

A durable correlation between an authenticated provider subject and an RE Principal.

Suggested logical fields:

```text
organization_id             -- tenant boundary when binding is tenant-scoped
principal_id                -- RE authority identity
provider                    -- e.g. workos, clerk, descope, oidc
provider_environment        -- stable environment/instance identifier, not a secret
provider_subject_id         -- external user/sub identifier
provider_organization_id    -- nullable provider org/tenant correlation
provider_membership_id      -- nullable provider membership correlation
status                      -- active/revoked/suspended/pending
last_seen_at
created_at
revoked_at
revision
```

Do not assume email is an identity key. Email can change and can be shared/reused. The stable provider subject plus provider environment is the credential-side identity.

A human may belong to multiple RE organizations. The design must decide whether that means one global external identity mapped to multiple tenant-scoped Principals or a reusable account identity plus tenant memberships. Preserve the current hard tenant boundary; do not weaken RLS to create a global mutable Principal unless the existing schema already safely supports it.

### 4.2 StaffMembership / Representation lifecycle

Prefer extending the existing Representation model instead of creating a parallel membership authority model if Representation already expresses the required semantics.

Required lifecycle:

```text
PENDING / INVITED
ACTIVE
SUSPENDED
REVOKED
```

The lifecycle must answer:

- who is a member of this Organization;
- what Party/authority anchor they represent;
- what operational scopes they hold;
- which capabilities are granted;
- who granted them;
- when/revision under which policy;
- whether the membership is currently executable;
- whether provider membership is merely correlated or required.

### 4.3 ProviderConnection / IdentityProviderConfiguration

Provider secrets must not be stored as ordinary domain data. Configuration should be injected by deployment/secret manager.

RE may persist only non-secret correlation/configuration facts needed for deterministic routing, for example:

```text
provider
provider_environment/issuer
provider_organization_id
webhook signing configuration reference (not secret value)
provisioning_mode
sync_mode
status
```

Suggested `provisioning_mode` values:

```text
provider_first
request_engine_first
linked_existing
```

Do not implement all modes in the first slice. The model should not prevent them.

## 5. Recommended authority topology

Treat authentication and business authorization as two independent gates:

```text
trusted provider credential/session
        ↓ verify signature/issuer/audience/expiry
provider subject
        ↓ resolve binding
Request Engine Principal
        ↓ tenant policy
capability grants
        ↓ contextual authority
Representation / operational scope
        ↓ owner validation
business command
```

A valid Clerk/WorkOS/Descope session with no active RE binding must produce a typed authentication/provisioning state, **not** an implicit all-powerful Principal.

## 6. Bootstrap problem: the first admin

This is the core circular dependency that must be solved explicitly.

Today `organization.bootstrap` assumes a freshly provisioned Principal and an active `organization` Party, then grants root operational scopes. That is insufficient for zero-to-one tenant creation.

The first-admin flow must create the minimum trust root without requiring an already-existing tenant admin.

### 6.1 Recommended bootstrap trust boundary

Create a **platform/deployment provisioning authority**, distinct from tenant administrator authority.

Examples:

- trusted backend signup service;
- verified provider webhook consumer;
- platform operator Principal;
- one-time provisioning token minted by the control plane.

This authority may call a narrow bootstrap command such as conceptually:

```text
tenancy.provision_organization
```

It must not receive ordinary tenant business capabilities.

### 6.2 Atomic internal bootstrap transaction

The internal RE transaction should create or reconcile, in one DB transaction where possible:

1. Organization;
2. organization Party;
3. initial Principal;
4. external identity binding;
5. initial active staff Representation/membership;
6. initial RE capability grants;
7. root operational Representation scopes;
8. audit/provenance record;
9. provisioning state / outbox intent.

Either all internal authority facts become visible together or none do.

Do not perform a WorkOS/Clerk/Descope network call while holding PostgreSQL locks or inside this transaction.

## 7. External provider creation must be a durable saga, not a distributed transaction

There is no safe ACID transaction across PostgreSQL and WorkOS/Clerk/Descope.

Use the repository's existing durable outbox/worker patterns.

Recommended state machine:

```text
REQUESTED
INTERNAL_PROVISIONED
PROVIDER_PENDING
ACTIVE
RECONCILIATION_REQUIRED
FAILED_TERMINAL
DEPROVISIONING
REVOKED
```

A minimal provider-first flow may skip provider creation but still needs reconciliation state.

### Request-Engine-first mode

```text
POST provisioning intent
    ↓ transaction
create internal tenant trust root + outbox(provider.organization.ensure)
    ↓ worker
create/reconcile provider organization + membership
    ↓ transaction
persist provider ids / binding / ACTIVE
```

### Provider-first mode

```text
provider creates user/org/membership
    ↓ signed webhook or trusted backend exchange
normalize provider event
    ↓ idempotent Tenancy command
create/reconcile RE Organization + Party + Principal + Representation/grants
    ↓ ACTIVE
```

Both paths must converge on the same owner command semantics.

## 8. Provider anti-corruption layer

Create provider-neutral contracts in Platform or a narrowly scoped identity integration package. Do not let Tenancy import WorkOS/Clerk/Descope SDK types.

Conceptual inbound normalized types:

```text
AuthenticatedExternalSubject
ExternalOrganizationRef
ExternalMembershipRef
ExternalInvitationRef
ExternalIdentityEvent
```

Conceptual provider port:

```python
class IdentityProviderPort(Protocol):
    async def ensure_organization(...): ...
    async def ensure_membership(...): ...
    async def invite_member(...): ...
    async def revoke_membership(...): ...
    async def resolve_subject(...): ...
```

Provider adapters:

```text
platform/identity_providers/workos.py
platform/identity_providers/clerk.py
platform/identity_providers/descope.py
```

Exact package names are not normative. Preserve repository ownership rules: vendor SDKs belong at an adapter edge, not inside Tenancy domain/application.

The first implementation should use a fake/in-memory provider adapter in tests and **one** real provider adapter as proof. Do not implement three SDK integrations simultaneously before the contract stabilizes.

## 9. Which provider to implement first

Recommendation: implement the generic OIDC/JWT authentication binding plus **one B2B provider integration**, then prove a second provider can satisfy the same port without schema changes.

Good candidates:

- WorkOS AuthKit: organization membership is explicit and suitable for B2B provisioning.
- Clerk: very polished B2B Organization UX and creator/admin flows.
- Descope: flexible tenant-scoped roles and useful agent/integration features.

Do not choose based on provider role features alone because RE will not delegate its business authorization model to provider RBAC.

Implementation order recommended for this branch:

```text
1. provider-neutral trust/binding model
2. generic verified external-subject resolver contract
3. WorkOS OR Clerk adapter
4. second-provider contract test (may be fake fixture initially)
5. Descope after the lifecycle contract is stable
```

## 10. Authentication adapter contract

The current HTTP architecture already uses `ActorResolver` and `ActorContext`. Preserve that boundary.

Add a provider-backed resolver that performs:

```text
verify credential/token
verify issuer
verify audience
verify expiry/not-before
extract immutable provider subject
extract provider org/tenant context if present
resolve ExternalIdentityBinding
ensure binding ACTIVE
load RE Principal + tenant grants
return ActorContext
```

Never accept `organization_id`, `principal_id`, capabilities or Representation scopes from an untrusted request body.

If a user is authenticated at the provider but not yet provisioned in RE, return a typed state such as `PrincipalProvisioningRequired`; do not mint a synthetic unrestricted ActorContext.

For users in multiple organizations, the active provider organization/tenant must map to exactly one RE Organization binding. Reject ambiguous/missing mapping rather than guessing from email/domain.

## 11. Staff administration API that must exist before Stage C can be called complete

Tenancy should expose owner-backed operations similar to the following semantic set. Final names must follow the canonical operation pattern already introduced on the branch.

### Queries

```text
staff_membership_list
staff_membership_read
staff_effective_authority_read
staff_invitation_list
identity_provider_binding_read
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
external_identity_binding_reconcile
```

Avoid `grant arbitrary capability` as the primary public API if it allows accidental privilege construction. Prefer a constrained authority assignment command that validates grantability policy.

## 12. Capability design

Do not create role-shaped capabilities such as `role.admin` or `role.receptionist`.

Recommended management capabilities are semantic actions, for example:

```text
organization.provision            -- platform/deployment only
staff.read
staff.invite
staff.manage_membership
staff.manage_authority
identity.bind
identity.reconcile
```

Existing business capabilities remain unchanged:

```text
organization.manage_profile
catalog.manage
booking.manage_supply
queue.configure
communications.configure
...
```

A business persona is a policy bundle, not a capability key:

```text
receptionist policy
    -> booking operational capabilities
    -> queue capabilities
    -> party lookup/register as justified
    -> NO catalog terms/profile authority unless explicitly granted

manager policy
    -> wider operations

admin policy
    -> staff management + configuration
```

## 13. Anti-escalation requirements

This feature is security-sensitive. The implementation is incomplete unless these are proven.

### 13.1 No self-escalation

A Principal must not be able to grant itself capabilities/scopes it does not have authority to delegate.

### 13.2 Grant ceiling

The grantor can only assign from an explicitly grantable set under the current policy. Possessing a business capability does not automatically imply permission to delegate it.

### 13.3 Last-admin safety

Decide explicitly whether removing/suspending the last tenant admin is allowed. Recommended default: reject unless a platform recovery path or another active admin exists.

### 13.4 Cross-tenant opacity

Foreign provider organization IDs, subject IDs, membership IDs, invitations and staff records must remain opaque across tenants.

### 13.5 Immediate RE revocation

Once a membership/binding/grant is revoked in RE, a still-valid external provider session must no longer authorize protected RE operations.

Provider logout/session revocation may lag; RE authorization must not depend on waiting for provider session expiry.

### 13.6 Webhook replay safety

Provider webhooks are at-least-once inputs. Persist provider event IDs/dedupe keys and make handlers idempotent.

### 13.7 Out-of-order events

Do not let an older `membership.updated` event resurrect a membership after a newer revoke/delete. Persist provider version/timestamp/event ordering metadata where the provider supports it; otherwise use reconciliation reads for ambiguous cases.

### 13.8 Provider compromise containment

A provider role claim must never directly become an arbitrary RE capability set. Translation policy must have a fixed allowlist/role mapping controlled by RE deployment/configuration.

## 14. Invitation lifecycle

Invitation is useful but must not be confused with authority.

Recommended lifecycle:

```text
invite requested
    ↓
RE durable StaffInvitation intent
    ↓ outbox/provider adapter
provider invitation created
    ↓
recipient authenticates/accepts
    ↓ webhook or trusted callback
provider subject correlated
    ↓
RE membership/Representation activated
    ↓
capabilities become effective
```

An invitation alone grants nothing.

Provider-managed invitation IDs/URLs are correlations, not the canonical authority object.

## 15. Webhook ingestion

Implement a provider-neutral ingress boundary with provider-specific signature verification adapters.

Never put provider payloads directly into Tenancy commands.

Flow:

```text
HTTP webhook
  -> verify provider signature
  -> validate timestamp/replay window
  -> deserialize provider payload
  -> normalize to ExternalIdentityEvent
  -> persist/dedupe provider event
  -> dispatch owner command
  -> record result/provenance
```

Return success for safely deduped replay according to provider retry expectations.

Useful normalized event families:

```text
user.created/updated/deleted
organization.created/updated/deleted
membership.created/updated/deleted
invitation.accepted/revoked/expired
```

Only implement event families needed by the first supported lifecycle.

## 16. Source-of-truth matrix

The implementation must document this explicitly.

| Fact | Recommended authority |
|---|---|
| password/passkey/MFA/session | identity provider |
| provider user ID | identity provider |
| RE Organization ID | Request Engine |
| RE Principal ID | Request Engine |
| Organization business Party | Request Engine |
| operational Representations | Request Engine |
| RE capabilities | Request Engine |
| provider org/tenant correlation | binding record |
| provider membership correlation | binding record |
| invitation delivery state | provider + reconciled RE intent |
| effective authorization to RE command | Request Engine |

## 17. Provisioning state and onboarding readiness

Extend Onboarding only with owner-backed facts. Do not make Onboarding execute provisioning.

Potential new readiness sections/blockers:

```text
identity
  provider_linked
  initial_admin_active

staff_administration
  admin_authority_ready
  staff_management_available
```

Suggested blockers:

```text
identity_provider_not_linked
initial_admin_missing
initial_admin_authority_incomplete
```

Resolution guidance should continue using `owner + resolution_capabilities`, not hardcoded operation IDs from Tenancy transport.

## 18. HTTP trust surfaces

Keep security primary at authorization, not network placement.

Recommended exposure:

```text
provider webhook endpoint                  deployment/provider ingress
organization provisioning                 platform/control plane only
staff membership/grant administration     authenticated admin/control plane
staff read                                operator/admin according to policy
normal business operations                existing public/operator surfaces
```

Do not expose `organization.provision` as a normal patient/public-agent tool.

The authorized operation catalog introduced on this branch should eventually surface staff-management operations only to actors whose effective capabilities permit them.

## 19. Database work sequence

Do not start with a giant migration.

### Phase P0 — schema audit

Before DDL, inspect current tables/functions/RLS around:

```text
organizations
principals
parties
representations
principal capabilities/grants
operational authority snapshots/revisions
idempotency/audit/outbox
```

Document which existing structure can express memberships and bindings and what is genuinely missing.

### Phase P1 — minimal binding + lifecycle schema

Add only the minimum structures/columns required for:

- external subject binding;
- provider org/membership correlation;
- active/suspended/revoked staff authority;
- provenance/revision;
- event dedupe/reconciliation if no suitable shared provider-event table exists.

### Phase P2 — RLS/grants

Every new tenant-owned table must have the same tenant opacity guarantees as current Tenancy state.

### Phase P3 — indexes/constraints

At minimum consider uniqueness for:

```text
(provider, provider_environment, provider_subject_id, organization mapping)
provider membership correlation
one active binding invariant where required
provider event id dedupe
```

Exact constraints must follow the resolved global-vs-tenant Principal model.

## 20. Test/proof plan

### Unit/domain

- binding normalization and identity key rules;
- lifecycle transitions;
- grant ceiling;
- no self-escalation;
- last-admin rule;
- provider role -> RE policy mapping cannot emit unknown capabilities.

### Integration

- provider resolver maps a verified subject to the correct ActorContext;
- wrong provider org context rejected;
- revoked binding rejected even with valid provider token;
- multi-org identity selects exact tenant, never first-match guessing;
- invitation acceptance activates exactly one membership.

### PostgreSQL

- atomic Organization + Party + first Principal + Representation/grants bootstrap;
- tenant RLS/foreign-row opacity for all new tables;
- concurrent duplicate provisioning produces one tenant trust root;
- concurrent invitation acceptance is idempotent;
- revoke races cannot resurrect authority;
- provider webhook replay is harmless;
- out-of-order provider events are rejected/reconciled correctly;
- audit/provenance facts commit atomically with authority changes.

### E2E

Prove a completely fresh environment using only supported APIs/adapters:

```text
1. external user authenticates
2. create/provision business tenant
3. first admin becomes active
4. admin configures Organization/Location/Offering/Resource/Queue/communications
5. admin invites receptionist
6. receptionist accepts/authenticates
7. receptionist can perform allowed Queue/Booking actions
8. receptionist cannot change staff grants or protected admin configuration
9. admin revokes receptionist
10. receptionist's still-valid provider session is denied immediately by RE
```

Repeat the identity portion with a second provider adapter or contract fixture to prove the domain is not vendor-shaped.

## 21. Failure semantics

Define typed failures; avoid generic 500s.

Examples:

```text
ExternalIdentityNotBound
ExternalOrganizationNotBound
PrincipalProvisioningRequired
OrganizationAlreadyProvisioned
MembershipAlreadyActive
MembershipRevoked
LastAdministratorRemovalRejected
GrantNotDelegable
ProviderEventReplay
ProviderReconciliationRequired
ProviderUnavailable
```

`ProviderUnavailable` must not roll back already-committed internal state if using the outbox saga. It should leave a recoverable provisioning state.

## 22. Observability

Emit correlation-friendly structured telemetry without secrets/token contents:

```text
provider
provider_event_type
provider_event_id hash/id where safe
organization_id
principal_id
provisioning_id
membership_id
state transition
attempt
result
correlation_id
```

Never log access tokens, refresh tokens, API secrets, invitation secrets, raw webhook signatures or sensitive JWT claims.

## 23. Provider-specific notes

### WorkOS

WorkOS AuthKit's Organization Membership is a good correlation target. Invitations can result in a user plus organization membership. Treat WorkOS roles as optional input to mapping policy, not RE authority.

### Clerk

Clerk can automatically make the creator the first Organization member/admin and supports custom roles/permissions and role sets. This is useful UX, but RE must still create its own Principal/Representation/grants. The Clerk `org:admin` claim must not directly mean `*` in RE.

### Descope

Descope supports users belonging to multiple tenants with per-tenant roles and can optionally isolate the same login ID per tenant. The RE adapter must not assume one global email = one Principal. Descope tenant roles are mapping inputs only.

## 24. Implementation slices / commits

The next agent should work in narrow, certifiable slices.

### Slice 0 — restore green branch

- apply Ruff formatting differences from CI #4285;
- exact-head CI;
- do not proceed if the failure is semantic rather than formatting.

### Slice 1 — current-schema and authority audit

Deliver:

- exact current tables/functions/RLS involved;
- current Principal provisioning path;
- current Representation/grant tables/commands;
- decision on tenant-scoped vs reusable/global external identity binding;
- ADR/update to this document if the schema changes the proposed model.

No speculative DDL before this audit.

### Slice 2 — provider-neutral identity contracts

Implement:

- external subject/binding domain types;
- provider adapter Protocol;
- fake adapter;
- normalized event types;
- architecture tests preventing vendor SDK imports into Tenancy domain/application.

No real provider SDK required yet.

### Slice 3 — zero-to-one Organization bootstrap

Implement one owner command capable of atomically creating/reconciling:

- Organization;
- business Party;
- initial Principal;
- identity binding;
- first active Representation/membership;
- bootstrap/admin capability set;
- operational authority scopes;
- audit/provenance.

Protect with platform-only capability/trust boundary and idempotency.

This slice closes the `business_party_missing` + `initial_admin_missing` circular dependency.

### Slice 4 — staff lifecycle

Implement:

- invite intent;
- list/read staff;
- activate/suspend/reactivate/revoke;
- replace constrained authority/grants;
- anti-self-escalation;
- last-admin protection;
- revision/idempotency semantics.

### Slice 5 — provider reconciliation/webhooks

Implement verified provider event ingestion, dedupe and state reconciliation using fake adapter first.

### Slice 6 — first real provider

Implement WorkOS **or** Clerk adapter end to end.

Do not introduce vendor objects into Tenancy contracts.

### Slice 7 — second-provider proof

Implement enough of a second provider adapter/fixture to prove no schema/domain redesign is needed.

### Slice 8 — onboarding/operation catalog integration

- expose identity/admin readiness facts;
- add canonical operation metadata;
- let authorized operation catalog discover staff operations;
- do not mark them as public tools by default.

### Slice 9 — adversarial E2E

Run the complete fresh-business + employee + revoke journey described above.

Only after this slice may docs claim administrative self-service is complete.

## 25. Definition of done

Do not call this feature complete until all of the following are true:

1. A fresh authenticated human can become the first administrator of a new RE tenant without SQL/manual fixtures.
2. Organization, business Party, Principal, provider binding and root authority are created atomically or by a recoverable documented saga where external I/O is involved.
3. An admin can invite/add, inspect, change and revoke staff through supported owner-backed operations.
4. An employee cannot self-escalate or delegate authority beyond policy.
5. A revoked employee is denied immediately by RE even if the identity-provider session remains valid.
6. Foreign tenant staff/bindings are opaque.
7. Provider webhook replay/out-of-order delivery cannot duplicate or resurrect authority.
8. At least one real provider integration works.
9. A second provider satisfies the same RE contracts without domain/schema redesign.
10. No provider SDK types leak into Tenancy domain/application contracts.
11. Onboarding reports the missing identity/admin prerequisites machine-readably.
12. Authorized operation discovery reflects the employee's effective RE capabilities.
13. Current semantic guarantees and PostgreSQL current-product proof remain green.

## 26. Things the next agent must NOT do

- Do not make Clerk/WorkOS/Descope the canonical source of Request Engine business authorization.
- Do not equate email with identity.
- Do not accept tenant/principal/capability identity from request bodies.
- Do not call providers while holding DB locks.
- Do not make invitations grant authority before acceptance/activation.
- Do not introduce `admin`, `receptionist`, `doctor`, etc. as hard-coded core capability semantics.
- Do not grant `*` because a provider claim says `admin`.
- Do not create a second membership authority model if existing Representation can correctly own it.
- Do not rewrite the baseline migration casually; schema remains controlled/mutable but requires the current audit/rebaseline discipline.
- Do not weaken RLS, idempotency, provenance or concurrency proofs to make provider integration easier.
- Do not resume MCP/tool projection until staff/identity authority is secure enough to determine who should see those operations.

## 27. First concrete command for the next agent

Start by inspecting the exact branch and CI, then fix the known formatting-only failure. After a green Python lane, inventory Tenancy persistence and commands for `Organization`, `Principal`, `Party`, `Representation`, capability grants and operational authority. Produce the Slice 1 disposition before writing provider integration code.

The strategic objective is not "support WorkOS" or "support Clerk". It is:

> Make Request Engine capable of safely provisioning a real business and its first administrator, then administering human staff authority through a provider-neutral identity boundary, while external authentication providers remain replaceable adapters rather than owners of Request Engine's business authorization model.
