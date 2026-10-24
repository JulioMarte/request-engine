# Native initial controller policy

> **Current scope (2026-10-11):** this document governs **tenant** initial-controller
> policy only. It does not define the new platform-owner policy from ADR 0014.
> Current application code selects `tenant-controller-v9` for new organizations
> (migration `0044_tenant_controller_v9`: v8 plus fifteen delegable operational
> front-desk capabilities; see "v9 front-desk authority" below). v8 (migration
> `0043_staff_invitation_proposals`) is v7 plus delegable operational
> `staff.propose_invitation`, ADR 0019. Existing roots reach v9 only through
> dual-consent adoption; apply accepts v1-v5→v6, v1-v6→v7, v1-v7→v8 (already
> recorded consent only) and v1-v8→v9.
> Immutable v1–v6 remain historical authority manifests, not rewritten defaults.

Schema authority: the immutable v1–v9 manifests are seed rows of the accepted
`0001_initial` baseline (2026-10-23 rebaseline, `docs/audits/postgresql-rebaseline-0047.md`).
Revision labels below (0021, 0039, 0040, 0043, 0044 and the older
0036/0037/0038/0053) are provenance from collapsed migration chains, not current
Alembic revisions or current release certification. Exact-head CI remains
authoritative.
Owner: Tenancy. Scope: new native organizations created by the private owner command.
This does not define a core administrator role or make platform authority tenant authority.

## Existing controller adoption (bounded, opt-in)

The accepted [ADR 0016](../adr/0016-existing-controller-policy-adoption.md)
adds a separate dual-consent journey for organizations whose immutable initial
policy is v1 through v6. The original active HUMAN root requests adoption through
`POST /v1/controller-policy-adoptions`; a current HUMAN platform operator with
the dedicated `platform.organization.adopt_initial_controller_policy` grant may
apply only that durable, unexpired consent through
`POST /v1/platform/controller-policy-adoptions/{request_id}:apply`. The root can
withdraw consent and inspect only its own request. A separately authorized
platform reader can list bounded pending requests, exposing only organization,
controller and policy/revision metadata needed to complete the handoff.

The command adds only missing tenant grants from the approved v1-v6 to v7 delta. Previously committed pending v1-v5 to v6
consent remains target-bound and can still be applied to v6; migration never
retargets consent.
It never backfills existing roots, restores a revoked grant, rewrites the original
root fact, grants platform authority to a tenant, or turns a platform operator
into tenant staff. Root consent requires the immutable root relationship, current
active binding and recent phishing-resistant HUMAN authentication. Application
requires the dedicated platform capability, current platform authority, a distinct
active native HUMAN identity and an unchanged root authority revision. Tenant
reads remain opaque to any principal other than that same active root controller.

This is not a silent migration or universal readiness claim. Existing organizations
remain unchanged until both actors complete the API journey. The onboarding
`recorded_policy_key` now reflects the latest successful adoption when present;
`current_policy_ready` is computed from the original controller's active grants,
including capability, authority plane, and delegability, so a later revocation or
semantic mismatch makes readiness false. Its reported authority revision belongs
to that same original controller. The feature is considered
implemented at the code/schema level only after the migration and real PostgreSQL
HTTP/adversarial proofs pass; deployment/publication evidence remains separate.

## Decision

The application selects `tenant-controller-v9` only while creating a new native
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
under that historical default, existing root control grants produced 50 active
grants on a fresh native root.

v7 is the immutable v6 manifest plus exactly one delegable operational Query:
`queue.read_configuration`. It permits bounded service-queue configuration
inventory under current Party `operations.manage_supply` scope; it grants no
queue mutation or platform authority. v7 contains 43 policy grants; together
with eight existing root-control grants a fresh root has 51 active grants.

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
recorded policy selection remains outside the v1-v6 transition contract and needs
a separately accepted governance operation. Deploy the
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


## v7 additive transition and local proof

Migration `0040_tenant_controller_v7` appends one private manifest row and expands
the two adoption target constraints to accept v6/v7. It preserves historical
functions' identity/recovery checks, authority revisions, lock ordering, revoked
grant rejection, receipt replay and existing ACLs. Function edits require unique
anchors and abort the transactional migration if the installed definition differs.
No principal, grant, root fact, pending request or adoption fact is backfilled.
Normal new consent targets v7; exact replay returns its previously recorded target.
Apply accepts only v1-v5 to v6 or v1-v6 to v7. V7 self-adoption is rejected.

Local PostgreSQL 18.6 evidence covers immutable v6/v7 manifests, fresh v7
provisioning, revocation-safe replay, all six legacy source policies, existing
native-auth adoption and (until the 2026-10-23 rebaseline removed its subject)
a physical populated 0039-to-head transition preserving old authority and
applying an original v6 consent. That populated-upgrade proof is historical: no
pre-rebaseline database can upgrade into the current baseline. Exact-head CI and
deployed schema/application compatibility remain separate.


## v9 front-desk authority (migration 0044)

Browser review showed a v8 clinic owner could not create a walk-in queue, run the
Today console's live queue or edit the business profile/contacts, and because
staff authority replacement forbids self-replacement and is capped at the actor's
delegable ceiling, nobody in the clinic could ever obtain that authority.
`tenant-controller-v9` is immutable v8 plus exactly these delegable operational
grants, each the capability of a current owner HTTP operation used by the Today
console, queue setup or the business profile:

| Capability | Owner operation(s) |
| --- | --- |
| `queue.configure` | `queue_service_queue_create` |
| `queue.list`, `queue.staff_read` | `queue_list`, `queue_staff_read` |
| `queue.check_in` | `queue_check_in` (reservation check-in and walk-in admission) |
| `queue.call_next`, `queue.skip`, `queue.mark_no_show` | live queue commands |
| `queue.operator_select`, `queue.recall_hold`, `queue.release_recall_hold` | triage commands |
| `service_session.start`, `service_session.complete` | start creates the ServiceSession the Today console completes |
| `appointments.confirm_attendance`, `appointments.record_arrival_estimate` | Today appointment actions |
| `organization.manage_profile` | `tenancy_organization_profile_update`, `tenancy_organization_contacts_replace` |

Deliberately excluded: `queue.join`/`queue.leave`/`queue.status` (subject-scoped
public operations; staff walk-ins use `queue.check_in`), `queue.manage_intake`
(no HTTP operation currently exposes it), `queue.subject_override` (not runtime
available), queue history/workload classification, service pause/resume/read,
resource activity and every platform-plane capability. v9 has 59 policy grants; a
fresh native root holds 67 active grants. Migration `0044` inserts one catalog row,
widens both adoption target constraints to v6-v9 and re-creates the consent/apply
definer functions through unique anchors; pending consent keeps its recorded
target. No existing principal, grant, root fact or consent is changed by the
migration. Proof: `tests/db/test_initial_controller_policy.py`,
`tests/db/test_tenant_controller_v9_adoption.py` (adoption delta on head; its former
populated 0043→head half became historical at the 2026-10-23 rebaseline),
`tests/e2e/test_tenant_controller_v9_front_desk_http.py` and the adoption HTTP
journeys in `tests/e2e/test_controller_policy_adoption_http.py`.
