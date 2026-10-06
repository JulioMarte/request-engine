# 0016 — Explicit adoption of a newer policy by an existing tenant controller

Status: Accepted — implementation present; exact-head production verification in progress
Date: 2026-10-04
Owner: Tenancy

## Context

The native provisioning default historically selected immutable
`tenant-controller-v3`. The accepted baseline also contains v4 and v5. A newer
manifest/default for future organizations is a CONTROLLED provisioning decision;
it does not change existing organizations, principals, grants or root facts.

There is **no supported existing API journey** that gives a sole v3 controller
new capabilities absent from its original policy. Creating another staff member
does not solve this: its authority is bounded by the same delegable ceiling.
Creating another organization cannot transfer authority across tenant boundaries.

`INV-CONTROLLER-POLICY-UPGRADE-001` is HARD. The existing tenant command requires
the current `controller_policy_upgrade` grant, a different HUMAN target and every
missing target capability inside the actor's current delegable ceiling. It rejects
revoked-grant restoration and stale revisions. These are intentional protections,
not checks to remove to make the UI work. A v3 controller does not hold the upgrade
capability; merely selecting v4/v5/v6 in an HTTP body cannot manufacture it.

The current initial-controller document's historical "platform ceremony"
reference is not evidence of an implemented platform policy-adoption API. Generic
platform owner lifecycle and organization creation authority do not authorize
arbitrary ongoing tenant authority mutation. An operator's provisioning provenance
is not standing tenant business membership.

## Decision

Implement a separate, **dual-consent, manifest-bounded bootstrap-policy adoption**
journey. The user explicitly authorized completion of the legacy-permission path.
That authorization accepts this narrow ongoing platform governance scope: one
currently authorized HUMAN platform owner may apply a policy delta only after the
active original tenant controller has independently consented. This remains a
Tenancy owner operation, not a parallel SQL/admin path, an exception inside staff
delegation, or an automatic grant migration. The API and durable facts are
implemented in migrations 0027/0029 and the Tenancy owner surface. Migrations
0030–0032 add tenant-scoped identity/binding foreign keys, reject a tenant
principal used as platform approver, and narrow SECURITY DEFINER functions to
reviewed column-level access. Migration 0033 adds a tenant-bound policy for
adoption facts without granting direct app table access. Isolated PostgreSQL
18.6 evidence currently covers the HTTP/native-auth journeys, replay,
RLS/least-privilege, revoked grants, tenant FK scope and the withdrawal-wins
apply race. Both lock orderings for apply versus withdrawal now pass local
PostgreSQL 18.6 tests using independent sessions and observed lock blockers.
Exact-head CI exposed the missing facts-table policy; migration 0033 adds it and
the focused RLS group passes locally. A later exact-head run exposed a stale
runtime table-privilege inventory, which is corrected on the branch. The new
exact-head run for that correction is still in progress. Concurrent platform
capability revocation is not proven.

### Recommended boundaries

1. The active original tenant HUMAN controller requests adoption of the approved
   immutable v1-v5 to v6 transition through `POST /v1/controller-policy-adoptions`.
   This durable consent is not the authority mutation. Admission requires the
   existing `organization.bootstrap` grant plus exact root relationship, current
   active native identity binding and recent verified phishing-resistant proof.
   The request records bounded reason/intent and expires after 24 hours; it does
   not mutate grants or widen the actor's delegation ceiling.
2. A current authorized HUMAN platform operator applies that exact request through
   `POST /v1/platform/controller-policy-adoptions/{request_id}:apply` under the
   dedicated `platform.organization.adopt_initial_controller_policy` capability.
   Possession of platform owner lifecycle, organization provisioning or the
   `platform.owner.provision` command capability alone does not authorize apply.
3. Consent and application must use distinct bound native identities; recovery-
   restricted, revoked, inactive or stale subjects cannot participate. This proves
   distinct accounts, not that two biologically different people control them.
   Stronger organizational separation is an operational governance decision.
4. The target is derived from the original organization's root provisioning fact
   and current native binding. Inputs cannot choose arbitrary staff, capabilities,
   authority planes, grantors or delegability. A replacement controller requires a
   separately accepted continuity/succession contract, not an inferred target.
5. Apply only the explicitly approved transition delta. Never restore a historically
   revoked capability, remove existing rights, promote a nondelegable existing grant,
   assign platform-plane authority to the tenant target, or grant operational tenant
   authority/membership to the platform operator. If a revoked delta capability is
   requested, block rather than resurrect it. Readiness must not claim a full target
   policy grant set when retained withdrawals mean that set is absent.
6. Both source policy selection and later adoption remain immutable provenance.
   Do not rewrite `organization_root_provisioning_facts.initial_controller_policy_key`.
   An append-only adoption fact records the original root, approved transition,
   both real principals, consent identity/revision, before/after authority revisions,
   time and correlation. A later transition uses the latest accepted adoption fact;
   the immutable original policy alone is not current adoption state.

### Platform capability reachability

A new capability in the registry is not usable authority. Do not silently backfill
it onto existing platform owners or assume a dormant selector grants it.
Migration `0026_platform_owner_v5` implements only this reachability prerequisite:
it appends immutable `platform-owner-v5` as the exact v4 grant list plus the
nondelegable `platform.organization.adopt_initial_controller_policy` capability,
changes the shared platform-owner provisioning selector so future provisioned
owners (including invitation activation) receive v5, and evolves the provisioning-
fact policy constraint to continue accepting historic v2 facts plus new v5 facts.
Migrations 0027–0033 now implement the tenant-consent and platform-apply
journeys, harden their tenant references, RLS policy and column ACLs, and add
database proofs for those boundaries. These migrations do not rewrite existing
facts.

The original first-claim owner remains `platform-owner-v1`; existing principals,
grants, revisions and provisioning facts are not backfilled or rewritten. Thus the
new apply capability is held only by owners created after this migration. The v1
root's existing `platform.owner.provision` authority can use the normal invitation
ceremony to activate a distinct new v5 owner, which closes capability reachability
without a grant backfill or self-upgrade. The v1 root itself cannot apply or
self-upgrade. This safe handoff depends on the existing owner invitation ceremony.
Do not substitute direct SQL grants or data reset.

### Implemented operation contract

| Item | Implemented contract |
| --- | --- |
| Business owner | Tenancy |
| Resource | `controller-policy-adoption` durable request plus explicit apply Command |
| HTTP | POST `/v1/controller-policy-adoptions`; GET `/v1/controller-policy-adoptions/{id}`; POST `/v1/controller-policy-adoptions/{id}:withdraw`; GET `/v1/platform/controller-policy-adoptions`; POST `/v1/platform/controller-policy-adoptions/{id}:apply` |
| Stable operation IDs | `controller_policy_adoption_request_create`; `controller_policy_adoption_request_get`; `controller_policy_adoption_request_withdraw`; `platform_controller_policy_adoption_list`; `platform_controller_policy_adoption_apply` |
| Capabilities | Tenant consent/get/withdraw require `organization.bootstrap` and exact root relation; platform list requires `platform.organization.read`; apply requires the dedicated adoption capability and exact current platform authority |
| Idempotency | Required per actor/semantic operation; current authority rechecked before every receipt |
| Concurrency | Explicit expected tenant authority revision and consent/adoption revision; one apply winner |
| Party/target authority | Original root relationship, current tenant controller consent, separately authorized platform actor |
| Schemas | Immutable policy keys, bounded reason, revisions; response contains request/fact IDs and real revisions, no secrets |
| Failures | 401 invalid session; 403 missing/current authority; opaque 404 unavailable request; 409 stale/conflicting/withdrawn consent; 422 invalid/unapproved transition |
| Tools | Optional projections of these typed owner operations; no second handler or tool-manufactured actor/tenant identity |

An ordinary tenant cannot inspect another tenant's request; unavailable foreign
request IDs return an opaque 404. The platform list is keyset bounded and contains
only pending, unexpired consent metadata, not tenant appointments, customers,
catalog or other business data. Apply/withdraw serialize against the canonical
tenant staff root and ordered active memberships before locking the adoption row.

### Consistency and migration gate

READ/PLAN the supported immutable transition and current owner-published state.
LOCK identity topology, the canonical tenant staff root, ordered active tenant
memberships and the adoption request consistently with existing staff writers.
VALIDATE both
current native authentication paths, principals, grants, binding/root relationship,
authority revisions and unexpired/unrevoked consent. WRITE delta grants, consume
consent, persist the immutable adoption fact/receipt and append truthful audit in
one Session and explicit transaction. EMIT no external consequence under locks.

Never pass a platform principal off as a tenant actor to satisfy an existing audit
schema. Fact/audit storage must support both real identities and authority sources.
SQL primitives provide only locks/structural consistency; Python retains command
semantics. Append new migrations; do not alter the baseline or existing policy
manifests. Existing roots receive no authority during schema installation/replay.

## Consequences

The ordinary tenant policy-upgrade/delegation guarantees remain unchanged. New
organizations use the reviewed v6 default. Existing v1-v5 organizations may opt in
through the dual-consent API; no legacy organization changes until its original
root consents and a separately authorized platform HUMAN applies the request.
The code/schema journey is implemented. Targeted adversarial PostgreSQL 18.6
proofs pass locally, including both apply/withdrawal orderings, but production
verification still requires exact-head CI and publication certification.
Apply/apply, apply-versus-authority-revocation and concurrent platform capability
revocation remain explicit proof gaps. This is not a reason to seed SQL or reset
tenant data.

The platform would gain a narrow ongoing role in tenant bootstrap governance.
Dual consent limits unilateral escalation but does not remove that authority
expansion. A self-hosted installation with one human controlling every account
cannot claim real two-person control merely by creating two identities.

## Rejected alternatives

- Automatic grant/backfill based on registry entries, policy insertion or replay.
- Removing self-target/ceiling checks from `controller_policy_upgrade`.
- Treating generic platform owner/provisioner authority as tenant authority.
- Temporarily setting platform actors to a tenant principal or accepting body-
  supplied trusted actor identities.
- Resetting/recreating existing tenants, mutating immutable policy/root facts or
  requiring direct SQL to access normal new features.
- Requiring a second tenant manager with capabilities no current tenant actor can
  legitimately delegate; that merely disguises the same unreachable authority.

## Required falsification evidence before acceptance/completion

- Real HTTP, native authentication and PostgreSQL 18 journey from existing v1-v5
  root, without manually seeded authority or expected-effect rows.
- Ordinary upgrade still rejects self-target, missing upgrade capability,
  nondelegable/outside-ceiling capabilities, revoked restoration and foreign target.
- Schema update, organization/claim replay and fresh default selection leave old
  root grants, original policy facts and authority revisions unchanged.
- Either participant's withdrawal, stale authentication/revision, expired/revoked
  consent, wrong source transition or same bound identity rejects with no effects.
- No arbitrary target, caller-supplied manifest, cross-tenant graft, workload actor,
  platform-as-tenant masquerade or operational grant to the platform participant.
- Independently synchronized apply/apply, apply/consent-revoke, apply/grant-revoke,
  apply/native-disable/recovery and platform-capability-revocation races; exactly
  one committed fact/receipt/audit and no revival on replay after authority
  withdrawal. Current proof covers both withdrawal/apply lock orderings;
  apply/apply, apply-versus-authority-revocation and platform-capability-
  revocation races remain outstanding.
- Runtime group/definer ACLs, RLS/foreign-row opacity, migration clean install and
  multi-database compatibility; current-product and exact-head CI evidence.
- Manual administrator journey shows old policy, requested delta, both consent
  states, blockers and the actual resulting rights without false readiness.
