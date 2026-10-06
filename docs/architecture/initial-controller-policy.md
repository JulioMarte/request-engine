# Native initial controller policy

> **Current scope (2026-10-04):** this document governs **tenant** initial-controller
> policy only. It does not define the new platform-owner policy from ADR 0014.
> Current application code selects `tenant-controller-v6` for new organizations.
> Immutable v1–v5 remain historical authority manifests, not rewritten defaults.

Current migration: `0021_tenant_controller_v6` appends v6 after
`0020_retention_recorder_role`. Historical 0036/0037/0038/0053 labels below are
provenance from the pre-rebaseline design chain, not current Alembic revisions
or current release certification. Exact-head CI remains authoritative.
Owner: Tenancy. Scope: new native organizations created by the private owner command.
This does not define a core administrator role or make platform authority tenant authority.

## Current limitation: existing controller adoption

The governed upgrade endpoint exists, but it does **not** let a sole existing v3
controller obtain capabilities outside its current delegable ceiling. That
controller also lacks `controller_policy_upgrade`, and the endpoint forbids
self-upgrade. No implemented platform "policy ceremony" currently resolves this
bootstrap gap. Creating staff or another tenant is not a legitimate workaround.
Changing the default for future organizations never upgrades existing ones.

Existing-root policy adoption therefore remains **pending governance**, not a
completed administration journey. [ADR 0016](../adr/0016-existing-controller-policy-adoption.md)
proposes a distinct bounded dual-consent design; it does not authorize new APIs,
capabilities, automatic grants or exceptions to
`INV-CONTROLLER-POLICY-UPGRADE-001`. Historical E1 validation below proves only
the deliberately preauthorized ordinary upgrade contract, not reachability from
an unmodified existing v3 root.

## Decision

The application selects `tenant-controller-v6` only while creating a new native
organization. A private transaction-local policy selection primitive validates
that exact approved policy exists before the existing atomic root command runs.
The root provisioning fact records the selected immutable policy key on INSERT;
the database materializes its explicit grants in that same transaction. The
policy's versioned manifest is durable data, not a query over the capability
registry. New registry entries never become new controller permissions implicitly.

v6 is an explicit reviewed manifest: immutable v5 plus thirteen delegable
operational capabilities. The eight new administration/readback capabilities are
`booking.read_supply`, `catalog.read_configuration`, `communications.read_configuration`,
`requests.create_definition`, `requests.publish_definition_version`,
`requests.set_definition_active`, `requests.read_definitions`, and `requests.read_inbox`.
Five already-existing capabilities complete these selected public journeys:
`communications.configure`, `requests.submit`, `requests.read`, `requests.cancel`,
and `requests.party_override`. The last is an explicit tenant-bound operator
authority override, not requester impersonation or a capacity/lifecycle bypass.
No registry wildcard or all-operator grant is used. v6 has 42 policy grants;
the existing root control grants produce 50 active grants on a fresh native root.

This is a pre-production ADAPT of the creation default, not an authority backfill.
No existing principal receives these grants from migration or provisioning replay.
`requests.record_result`, `requests.complete`, and `requests.fail` are deliberately
not added: they need a separately governed system/worker HTTP composition, not an
ordinary operator grant or automatic exposure of internal processing endpoints.
Existing organizations remain subject to the governance blocker above.

Keep the existing eight tenant-control grants and four operational Representations.
The original immutable v1 policy adds the following explicitly delegable grants:

| Authority plane | Additional capabilities |
| --- | --- |
| Tenant control | `agent.policy.read`, `agent.manage_policy`, `integration.provision`, `integration.read`, `integration.manage_authority`, `integration.suspend`, `delegation.create`, `delegation.revoke` |
| Operational | `organization.bootstrap`, `catalog.manage`, `booking.manage_supply`, `discovery.manage`, `onboarding.read`, `business.get_info`, `catalog.search_offerings`, `catalog.get_offering_details`, `parties.register`, `parties.lookup`, `appointments.find_slots`, `appointments.book`, `appointments.read`, `appointments.cancel`, `appointments.reschedule`, `appointments.subject_override`, `appointments.day_board` |

Revision 0037 appends v2: the same manifest plus delegable tenant-control
`agent.read` (26 additional grants, 34 active grants in total). It only inserts
one private catalog row, with no table rewrite, privilege change or root backfill.
The v1 manifest and existing roots remain unchanged. This is an explicit reviewed
default, not automatic inheritance of capability registry additions.

These grants support configuration, the native booking journey and bounded
human/agent/integration assignment. They do not imply all Request Engine operations.

Revision 0038 appends v3 = immutable v2 plus delegable operational
`authority.read_self`, for 35 active grants on new roots. This permits the
[self-authority relationship read](self-authority-inspection.md), not arbitrary
Principal or resource administration. No existing grants or root facts change.
The appointment subject override is explicit and tenant-bound; it is not a bypass
of capacity, lifecycle, revision, idempotency or owner checks. Workloads still
receive only the authority their HUMAN sponsor explicitly assigns, and AGENT
policy/risk checks remain separate. No platform-plane grant is included.

Revision 0053 appends v4 = immutable v3 plus delegable tenant-control
`controller_policy_upgrade`, the dedicated capability for the governed
[controller-policy upgrade](auth-production-completion-plan.md) command. It is an
explicit engineering decision made while the product is pre-production: without a
policy that grants the capability, the command is unreachable because the command
requires an active `controller_policy_upgrade` grant (`assert_staff_manager`).
v4 grants only that one operational capability; it adds no product capability and
does not widen the earlier manifest. It exists so a legitimately authorized tenant
operator can run the E1 upgrade ceremony; it is not an automatic backfill. Existing
roots keep their original selected policy and receive no new grant, and no platform
ceremony is performed by the migration. This is a deliberate, documented deviation
from the "no new policy version" default of the E1 plan section; the reason is that
the command would otherwise be dead code for every current root.

## Replay, compatibility and rollout

Previously created roots retain their original policy, including the absence of
this newer policy. Do not backfill, upgrade or restore their grants on replay.
Changing the default policy in a future application version must not rewrite a
previously committed root. Existing low-level root commands retain their minimum
policy when no explicit transaction-local selection is supplied; ordinary HTTP
creation always selects the approved manifest. The HTTP body cannot select
capabilities, a policy manifest, a Principal, an authority plane or a grantor.

Policy manifests and the root's selected policy are immutable provenance. A policy
change appends another version; it does not edit v1. Upgrading an existing root or
staff Principal now has a separate governed command
(`POST /v1/controller-policy-upgrades`, revision 0053) that adds only the target
policy's missing capabilities within the actor's current delegable ceiling; it is
never a silent authorization and it never restores a revoked grant. A root with no
recorded policy selection needs a separately accepted governance operation; no
implemented platform policy-adoption ceremony should be inferred. Deploy the
additive migration before the new application. The
private process must check the selection function is callable and the owner-selected
version exists at startup and readiness, failing closed on an older schema. Roll
forward; do not rewrite or downgrade applied history.

This private-process rollout requires a controlled maintenance window: the older
0035 process intentionally rejects the selector as an unexpected callable
privilege, while the newer process requires it. Drain the private provisioning
endpoint, apply 0036, replace that process and require readiness before reopening
it. Do not claim zero-downtime mixed-version private-control deployment. The
ordinary native tenant API does not gain this private function privilege.

## Connection and consistency design

READ authenticated subject and current platform authority; PLAN native identities,
idempotency intent and the application-selected policy; select that approved
policy transaction-locally; LOCK creator then native identity through the existing
root command; VALIDATE current HUMAN/plane/revision/capability and credentialed
target; WRITE Organization/Party/Principal/binding/membership/grants; EMIT the root
fact and immutable selected-policy provenance in that same transaction.

This is a CONTROLLED initial provisioning policy change preserving HARD authority,
tenant equality, atomicity, idempotency, privilege and provenance guarantees.
The policy catalog is private global configuration, never tenant-owned state.
No direct app/worker table grant, public callable function or external network I/O
is introduced. The private selector grants no authority by itself: only the
existing authorized root creation boundary can insert the root fact.

DDL adds nullable provenance to existing roots without rewriting/backfilling
them, then establishes the default only for future INSERTs. Trigger installation
takes the normal bounded schema lock. There is no production-scale data transform.

## Required falsification evidence

- The HTTP bootstrap-to-native-controller journey configures bookable supply and
  governs an integration/agent without manually seeding manager capabilities.
- Catalog keys match existing capability authority planes; the expected manifest
  is checked independently, never computed from the code under test.
- Unknown selected policies and invalid native targets roll back all root effects.
- Same-key concurrency creates one root and one initial grant set.
- Replaying after revocation does not restore authority; pre-policy roots remain
  unchanged after upgrade/replay.
- Manifest/root-policy mutation and app/worker direct access are rejected.
- Runtime role topology, current-product PostgreSQL 18 and Python-quality pass.

## Agent creation handoff

The native controller journey also governs an AGENT using the same initial policy.
Tenancy's existing command `POST /v1/agents` (`agent_provision`, `agent.provision`)
now returns `authority_revision` separately from `profile_revision`. The former
is the actual Principal revision read in the creation transaction under an explicit
tenant predicate, then recorded in the idempotent result. It is not a guessed
initial value or a synonym for the profile revision. There is no new capability,
database privilege, migration or tool projection for this response addition.
HUMAN/sponsor authority, required idempotency and existing failure semantics remain.

Clients can provision, assign bounded authority while pending, set agent risk/tool
policy, and activate using only HTTP-returned revisions. Provisioning responses
are `Cache-Control: no-store`. Replays retain the original revisions and never
repeat the workload secret; they do not pretend to be current-state queries.
Older persisted replay records without the new field return `authority_revision:
null`, not a fabricated revision or a re-executed provisioning command. Complete
agent inspection/refresh is provided separately by `agent_list` / `agent_get`
under explicit `agent.read`; see `agent-governance-inspection.md`. Clients must
not retry stale revisions blindly or treat creation replay as a refresh.

This contract does not certify completion of all required validation or production
acceptance. Track executed evidence in `auth-implementation-status.md`.
