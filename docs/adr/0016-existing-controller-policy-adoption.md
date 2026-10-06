# 0016 — Explicit adoption of a newer policy by an existing tenant controller

Status: Proposed
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

## Decision — proposal, not authorization

Recommend a separate, **dual-consent, manifest-bounded bootstrap-policy adoption**
journey. It must remain a Tenancy owner operation, not a parallel SQL/admin path,
an exception inside staff delegation, or an automatic grant migration. Acceptance
requires a user/product decision about the platform's ongoing governance scope.
No policy-adoption capability, grant, HTTP endpoint or application path is approved
or implemented by this ADR.

### Recommended boundaries

1. The active original tenant controller requests adoption of an explicitly
   approved immutable source-to-target policy transition. This is durable new
   demand/consent, not the authority mutation itself. Candidate admission is its
   existing `staff.manage_authority` standing grant plus controller/root relationship,
   with recent verified native authentication. Extending that capability to this
   narrow consent intent is itself a CONTROLLED decision requiring acceptance.
2. A current authorized HUMAN platform operator approves/applies the exact request
   under a dedicated proposed capability such as
   `platform.organization.adopt_initial_controller_policy`. Possession of platform
   owner lifecycle or organization provisioning alone must not imply this right.
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
An explicitly reviewed newer immutable platform owner policy and owner activation
selection could let an existing authorized owner invite/approve a **new** owner
through the existing owner ceremony. That new owner would receive the approved
policy by the supported owner operation, not by a hand-seeded grant. Existing
owners would still need an independently accepted policy-adoption path if they
must acquire this right themselves. This entire reachability change remains
proposed; its policy contents, admission and continuity must be reviewed first.

### Candidate operation gate

| Item | Proposed contract |
| --- | --- |
| Business owner | Tenancy |
| Resource | `controller-policy-adoption` durable request plus explicit apply Command |
| Candidate HTTP | POST `/v1/controller-policy-adoptions`; POST `/v1/platform/controller-policy-adoptions/{id}:apply` |
| Stable operation IDs | `controller_policy_adoption_request_create`; `platform_controller_policy_adoption_apply` |
| Capabilities | Tenant consent admission above; dedicated platform capability above; both pending acceptance |
| Idempotency | Required per actor/semantic operation; current authority rechecked before every receipt |
| Concurrency | Explicit expected tenant authority revision and consent/adoption revision; one apply winner |
| Party/target authority | Original root relationship, current tenant controller consent, separately authorized platform actor |
| Schemas | Immutable policy keys, bounded reason, revisions; response contains request/fact IDs and real revisions, no secrets |
| Failures | 401 invalid session; 403 missing/current authority; opaque 404 unavailable request; 409 stale/conflicting/withdrawn consent; 422 invalid/unapproved transition |
| Tools | Optional projections of these typed owner operations; no second handler or tool-manufactured actor/tenant identity |

The final resource names, required recent-authentication proof, consent expiry,
revocation operation, compatibility and audit shape must be accepted before code.
An ordinary tenant cannot inspect another tenant's request. Platform inspection
must be separately authorized and expose only the metadata needed for governance,
not tenant appointments, customers, catalog or other business data.

### Consistency and migration gate

READ/PLAN the supported immutable transition and current owner-published state.
LOCK identity topology and ordered platform/tenant serialization roots consistently
with existing provisioning, staff and native recovery commands; exact order needs
an explicit cross-plane deadlock review before implementation. VALIDATE both
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
organizations can adopt a reviewed fresh default without solving this governance
question. Existing v3 organizations remain unable to use newer capability-gated
features until an authorized adoption design is accepted and implemented. This is
a visible product limitation, not production readiness or a reason to seed SQL.

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

- Real HTTP, native authentication and PostgreSQL 18 journey from an existing v3
  root, without manually seeded authority or expected-effect rows.
- Ordinary upgrade still rejects self-target, missing upgrade capability,
  nondelegable/outside-ceiling capabilities, revoked restoration and foreign target.
- Schema update, organization/claim replay and fresh default selection leave old
  root grants, original policy facts and authority revisions unchanged.
- Either participant's withdrawal, stale authentication/revision, expired/revoked
  consent, wrong source transition or same bound identity rejects with no effects.
- No arbitrary target, caller-supplied manifest, cross-tenant graft, workload actor,
  platform-as-tenant masquerade or operational grant to the platform participant.
- Independently synchronized apply/apply, apply/consent-revoke, apply/grant-revoke
  and apply/native-disable/recovery races; exactly one committed fact/receipt/audit
  and no revival on replay after authority withdrawal.
- Runtime group/definer ACLs, RLS/foreign-row opacity, migration clean install and
  multi-database compatibility; current-product and exact-head CI evidence.
- Manual administrator journey shows old policy, requested delta, both consent
  states, blockers and the actual resulting rights without false readiness.
