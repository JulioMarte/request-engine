# Tenancy module

Owns `Organization`, `Principal`, `Party`, and `Representation` semantics and local authority materialization.

Primary concerns: hard tenant boundary, authority snapshots/revocation coordination, actor/party distinction, and exact policy/representation provenance.

Other modules consume only public tenancy contracts; participant roles or external correlations never become authorization by implication.

## Private platform provisioning

`api/native_platform_provisioning.py` owns native provisioner and organization-root
creation transport; `api/platform_provisioner_management.py` owns the provisioner
read projection and lifecycle transport (`list`/`get`/`suspend`/`reactivate`/`revoke`).
`api/platform_organization_reads.py` owns the private platform organization
projection (`GET /v1/platform/organizations` and
`GET /v1/platform/organizations/{organization_id}`) under the explicit
`platform.organization.read` capability. The projection is read-only, keyset
paginated, never exposes tenant-internal authority, and returns `404` for an
absent organization without creating a second organization authority path.
Their typed application commands and queries execute through the dedicated
platform-control and platform-read DB connections. The separate HTTP entrypoint only
composes that supported API. See `docs/architecture/http-runtime-deployment.md` for
operation IDs, authentication, idempotency, revision, privilege and transaction
contracts. Native enrollment alone still grants no Principal or tenant authority, and
a provisioner does not become a member of the tenant it creates. Lifecycle changes
are revisioned, replayed idempotently, recorded in a private append-only audit fact
and protected by the last-platform-controller guard; reactivation never restores
revoked authority.

Native organization creation selects the versioned initial controller policy
documented in `docs/architecture/initial-controller-policy.md`. Its explicit
grants and policy provenance are atomic with the root; replay never upgrades
legacy roots or restores revoked authority. New capabilities are not inherited
automatically from the runtime registry.

Agent provisioning returns separate profile and authority revision snapshots,
allowing initial authority assignment without database access. Idempotent replay
preserves the original revisions and omits the one-time credential; historical
responses without an authority revision return null. This is not a current-state
inspection API. Separate `agent_list` / `agent_get` reads expose current profile
and authority revisions plus standing capabilities under current HUMAN
`agent.read` authority. They do not expose credentials or claim effective access
to every Party/resource. See `docs/architecture/agent-governance-inspection.md`.

`GET /v1/me/authority` exposes the caller's current active Party relationships,
scopes and revisions under explicit operational `authority.read_self` authority.
It is self-only, bounded and advisory; it is not an arbitrary resource authorization
oracle. See `docs/architecture/self-authority-inspection.md` for the pending-validation
contract and immutable initial controller v3 policy.

## Identity binding inspection

`GET /v1/identity-bindings` and `GET /v1/identity-bindings/{binding_id}`
(`identity_binding_list` / `identity_binding_get`) expose the caller tenant's
identity bindings under explicit `identity.binding.read` authority: binding id,
principal id, authority id, status, revision and creation time. The projection is
tenant-opaque (a foreign or absent binding is indistinguishable and never
addressable), never exposes the binding subject or any verifier, and performs no
mutation.

## Identity binding lifecycle

`POST /v1/identity-bindings/{binding_id}:suspend`, `:reactivate` and `:revoke`
(`identity_binding_suspend` / `identity_binding_reactivate` /
`identity_binding_revoke`) own the tenant-local binding lifecycle under explicit
`identity.bind` authority (HUMAN only, `expected_revision`, `Idempotency-Key`).
Suspend/reactivate move an active binding to suspended and back; revoke is
terminal and never resurrects the row. Each command acquires the identity-topology
gate and the ordered active-staff-membership lock root before the specific binding
row, revalidates tenant controller continuity, and cannot remove the last
authenticatable controller. See
`docs/architecture/auth-production-completion-plan.md` (D1b) and
`docs/adr/0013-identity-security-decision-gates.md`.

## Party registry (S0b)

Owns `parties.register`, `parties.add_contact_point`, `parties.confirm_contact_point`,
the operator-granted corrections (`parties.rename`, `parties.add_document`,
`parties.deactivate_contact_point`, `parties.deactivate`),
`parties.rollback_identity`, `parties.lookup` and `parties.read_revisions`
(contract: `docs/v3/38-s0b-party-registry-contract.md`, §9 for the R2
authority/platform model). A Party is identity-only — never a CRM profile.
Attribution records two orthogonal durable facts: `source_kind`
(`operator`/`subject` — whose authority produced the change, derived from the
effective principal's kind; an integration principal relayed through an
admitted acting operator attributes to the operator) and `platform` (declared
by the trusted layer, never an authorization input). Every contact point is
created verified (§9.2); the confirm command remains for secondhand
information paths and the DB guard rejects downward flips. Phone lookup is
multi-match by design (shared family numbers). Identity documents
(cédula/passport) are unique per tenant, kind and normalized value. Correction
capabilities are grant-gated operator-only; bots hold only
register/add_contact_point/lookup, and bot-created Parties get a
"WhatsApp <number>" placeholder name corrected via `parties.rename`. Every
party mutation appends one full-identity revision to the append-only
`party_identity_revisions` ledger in the same transaction (§9.3); rollback
applies a prior snapshot as a new revision while verification stays monotone.

## Business onboarding authority (docs/v3/44)

`organization.bootstrap` allows a freshly provisioned principal to establish
the tenant's root operational authority through
`POST /v1/organization/bootstrap-operational-authority`: it grants the four
`operations.manage_*` scopes as delegated Representations on an active
`organization` Party. It is bootstrap-only (idempotent replay, no general
Representation administration) and exposes the owner-backed
`has_active_organization_party` fact consumed by `GET /v1/onboarding/readiness`.

## Identity-aware onboarding facts (E2)

Tenancy also publishes `contracts/onboarding_readiness.py`:
`has_active_organization_party` plus a tenant-scoped, PII-free
`OnboardingIdentityFactsReader`. The reader projects aggregated
identity/control facts (active controller, authenticatable controller,
recorded-policy readiness, staff-administration availability, observed time and
useful revisions) through the read-only SECURITY DEFINER function
`request_engine.read_onboarding_identity_facts`, which refuses any organization
other than the transaction's current tenant. The `GET /v1/onboarding/readiness`
projection itself is Onboarding-owned HTTP composition over the published
readers of Tenancy, Catalog, Booking, Queue and Communications; Tenancy does not
own that router.

## Staff administrative contacts (R2)

Staff (operator) principals register their OWN administrative contact
(`staff.manage_own_admin_contact`) and confirm it with a one-time 6-digit code
(`staff.confirm_own_admin_contact`; contract: `docs/v3/38` §9.2). RE owns the
durable intent: the code is stored only as a sha256 hash with a 15-minute
expiry and a 5-attempt limit, and ONE outbox event
(`staff.contact_verification_requested.v1`) carries the code verbatim as
transactional intent — delivery stays external (outbox → webhook transport →
WhatsApp). Verification is mandatory here, unlike patient contact points,
which are verified by provenance. `principal_id` is forced from the
authenticated actor; integration/relay callers get a typed 403. Replay of the
verification request never re-exposes a code, and the 0025 DB guard keeps
`verified` monotone even against direct SQL.

## Staff email invitations

`POST/GET /v1/staff/invitations` and the invitation detail/resend/revoke APIs
manage expiring invitations under current HUMAN `staff.invite` / `staff.read`.
Acceptance is a pre-tenant native-session operation requiring proof possession,
not email matching. It activates membership with no standing grants; authority
uses the existing preview/apply commands afterward. Communications receives a
closed-purpose delivery intent through an injected typed outbound port in the
same transaction. No patient Party/contact or second authentication path is
created. See `docs/architecture/staff-email-invitations.md` for lifecycle,
replay, delivery ambiguity, lock and deployment contracts.

`POST /v1/staff/invitations/{invitation_id}:preview` lets the authenticated native
recipient review the organization display name and invitation expiry using the
same proof, without creating membership or grants. It rejects tenant/query
selectors and returns an advisory, no-store projection; acceptance independently
revalidates current proof and authority.

## Staff administration reads

Tenant-local staff display labels are updated through `staff_profile_update`
(`PATCH /v1/staff/members/{membership_id}/profile`) and projected by the existing
`staff_list` / `staff_get` reads. The profile revision is independent from
membership and authority revisions; missing profiles remain unnamed. See
`docs/architecture/staff-member-profiles.md` for the capability, privacy,
literal-search, transaction, replay and narrow PostgreSQL privilege contract.

`GET /v1/staff/members` (`staff_list`) accepts optional membership `status`
(`invited`, `active`, `suspended`, `revoked`). Tenancy owns this resource Query
under existing current HUMAN `staff.read` authority. The filter is applied in
the same tenant-authorized SQL statement before UUID ordering and the bounded
limit; it does not narrow the organization-wide `staff_overview_get` counts.
No idempotency key, revision, authoritative lock, external connection, audit
write or tool projection is introduced. Invalid transport statuses receive 422;
revoked read authority still receives 403, and foreign rows remain invisible.
The admin projection forwards the filter to this API, preserves it across page
links and starts at page one when the selected filter changes. This additive
Query evolution preserves tenant opacity, current-authority rechecks and the
existing distinction between membership state and effective access.

`GET /v1/me/organizations` (`self_organization_list`) discovers only the
authenticated HUMAN subject's active organization memberships before tenant
selection. It rejects tenant/subject selectors and recovery-restricted sessions;
it never grants tenant authority. See
`docs/architecture/self-organization-discovery.md` for the authentication,
pagination, database privilege and API-only admin projection contract.

`GET /v1/staff/overview` summarizes membership lifecycle counts for the current
tenant under `staff.read`. `POST /v1/staff/members/{membership_id}/authority:plan`
is a revision-bound, read-only preview under query capability
`staff.plan_authority`; existing `staff.manage_authority` grants remain accepted
for that narrower preview. The plan returns only target grants inside the
caller's current delegable ceiling, reports requested capabilities outside that
ceiling as blocked, and never writes authority, audit, or idempotency state. The
authoritative `PUT .../authority` command independently revalidates its revision,
ceiling, controller continuity, and tenant state while holding its normal locks.
Replacement preserves target grants outside the caller's ceiling. Its controller
guard evaluates the actual post-replacement authority, including those preserved
grants. `assignable` describes ceiling compliance only; `can_apply` also requires
current apply authority and no revealable lifecycle/self/controller blocker.
Planning permission alone never implies permission to execute the command.

The planner's controller projection uses
`request_read.staff_controller_is_effective(principal_id)`. It derives the tenant
and HUMAN planner from trusted transaction context, rechecks active membership
and planning/managing authority, and reveals no foreign controller. The internal
two-argument controller predicate is not executable by the application role.
