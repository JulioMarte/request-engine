# V3 Party-authority adversarial closure inventory

Status: Phase 6I closure proven on the current branch. This document freezes the runtime Party-authority surface that closes R23 and the Party-authority portion of G06. Final V3 promotion must rerun the same inventory on the frozen release candidate.

## Security claim

Authentication, action capability, tenant RLS and possession of an aggregate identifier are not Party authority. A runtime operation with `party_scope` must establish one of exactly two authority paths:

1. a current exact-scope `Representation` for the authenticated Principal and target Party; or
2. an operator override capability declared by the canonical capability registry and derived from the authenticated actor.

A caller-supplied boolean is never authority. Public request bodies do not control override state.

For material mutations, authority is established inside the same tenant transaction as the write and before stale-revision/lifecycle information is exposed:

```text
idempotency replay
  -> lock caller-selected aggregate / required lock roots
  -> resolve target Party from the authoritative aggregate when one exists
  -> lock exact-scope Party authority (or explicit authenticated operator override)
  -> expected revision
  -> lifecycle/dependent invariants
  -> mutation + audit/outbox
  -> idempotency completion
  -> commit
```

Creation commands that necessarily receive a Party before an aggregate exists must validate the tenant-local Party/reference and exact creation scope inside the same authoritative transaction.

## Frozen runtime Party-scoped surface

| Capability | Kind | Party source | Exact scope | Operator override capability | Material mutation |
| --- | --- | --- | --- | --- | --- |
| `appointments.book` | command | request `subject_party_id` before Reservation exists | `appointments.book` | `appointments.subject_override` | yes |
| `appointments.read` | query | Reservation subject | `appointments.manage` | `appointments.subject_override` | no |
| `appointments.cancel` | command | locked Reservation subject | `appointments.manage` | `appointments.subject_override` | yes |
| `appointments.reschedule` | command | locked Reservation subject | `appointments.manage` | `appointments.subject_override` | yes |
| `appointments.confirm_attendance` | command | locked Reservation subject | `appointments.manage` | `appointments.subject_override` | yes |
| `queue.join` | command | request `subject_party_id` before QueueEntry exists | `queue.join` | `queue.subject_override` | yes |
| `queue.status` | query | QueueEntry subject | `queue.manage` | `queue.subject_override` | no |
| `queue.leave` | command | locked QueueEntry subject | `queue.manage` | `queue.subject_override` | yes |
| `waitlist.join` | command | request `subject_party_id` before WaitlistEntry exists | `waitlist.join` | `waitlist.subject_override` | yes |
| `waitlist.read` | query | WaitlistEntry subject | `waitlist.manage` | `waitlist.subject_override` | no |
| `waitlist.leave` | command | locked WaitlistEntry subject | `waitlist.manage` | `waitlist.subject_override` | yes |
| `waitlist.accept_offer` | command | SlotOffer -> WaitlistEntry subject | `waitlist.manage` | `waitlist.subject_override` | yes |
| `waitlist.decline_offer` | command | SlotOffer -> WaitlistEntry subject | `waitlist.manage` | `waitlist.subject_override` | yes |
| `reminders.create_plan` | command | request `subject_party_id` before ReminderPlan exists | `reminders.manage` | `reminders.subject_override` | yes |
| `reminders.read` | query | ReminderPlan subject | `reminders.manage` | `reminders.subject_override` | no |
| `reminders.cancel_plan` | command | locked ReminderPlan subject | `reminders.manage` | `reminders.subject_override` | yes |
| `requests.submit` | command | request `requester_party_id` before Request exists | `requests.submit` | `requests.party_override` | yes |
| `requests.read` | query | Request requester Party | `requests.manage` | `requests.party_override` | no |
| `requests.cancel` | command | locked Request requester Party | `requests.manage` | `requests.party_override` | yes |

The operator override capabilities themselves are `runtime_available=false`; they are permissions carried by the authenticated actor, not independently invokable HTTP commands.

## Exact-scope race inventory

R23 is closed by proving every distinct material exact-scope authority root, not by duplicating the same race for every endpoint that shares one scope. Each representative mutation below uses independent PostgreSQL/runtime transactions, deliberate overlap and final-state/cardinality assertions.

| Exact scope | Representative material command | Deterministic revoke race | Phase 6I result |
| --- | --- | --- | --- |
| `appointments.book` | `appointments.book` | yes | retained and passing |
| `appointments.manage` | `appointments.cancel` | yes | added and passing |
| `queue.join` | `queue.join` | yes | retained and passing |
| `queue.manage` | `queue.leave` | yes | added and passing |
| `waitlist.join` | `waitlist.join` | yes | retained and passing |
| `waitlist.manage` | `waitlist.accept_offer` / `waitlist.decline_offer` | yes | added; authority now precedes revision/lifecycle |
| `reminders.manage` | `reminders.cancel_plan` | yes | added and passing |
| `requests.submit` | `requests.submit` | yes | retained and passing |
| `requests.manage` | `requests.cancel` | yes | added and passing |

The race family demonstrates both serialized winner orders:

- command establishes current authority first -> revoke/deactivation cannot pass the locked authority root until the command commits; the command may complete once;
- revoke/deactivation wins first -> the material command cannot establish authority and produces no authoritative side effect.

## Adversarial denial matrix

The current branch has executable coverage for the relevant Party-authority denial cases across the frozen public surface and shared primitives:

- missing Representation;
- wrong exact scope (no wildcard, prefix or family inheritance);
- revoked Representation;
- future `valid_from`;
- expired `valid_until` using PostgreSQL wall clock;
- inactive Principal;
- inactive Party;
- foreign tenant Party/aggregate;
- nonexistent identifier control for foreign-identifier probes;
- same-tenant wrong Party;
- action capability without subject authority;
- operator action capability without the declared override capability;
- declared override capability restricted to the current tenant by RLS/reference validation;
- PartyRelationship/contact/correlation data never inferred as Representation.

Queries need no authority row lock because they create no material business effect, but they still derive the target Party from authoritative tenant state and do not bypass RLS or exact-scope checks.

## Phase 6I defects found and resolved

The inventory exposed two concrete defects and both are resolved on this branch:

1. **SlotOffer state oracle ordering.** `waitlist.accept_offer` and `waitlist.decline_offer` previously exposed revision/lifecycle checks before `waitlist.manage` authority. The command flow now preserves the canonical Opportunity -> Offer lock topology, then establishes Party authority before revision/status/expiry disclosure. Regression tests prove an unauthorized caller cannot use stale revisions as a state oracle.
2. **Reminder invalid-reference HTTP fallback.** `RecipientNotFound` is an expected tenant-reference failure for the public ReminderPlan surface but previously fell through to the generic Communications HTTP 500. It now maps to opaque `tenant_reference_not_usable` / `fix_request` without echoing the probed Party UUID, and foreign versus nonexistent Party controls are equivalent.

## G06 protected-function inventory

The tenant-isolation gate also requires the app executable-function surface to be explicit rather than relying on sample permission checks. `tests/db/test_v3_app_function_privilege_inventory.py` creates a real LOGIN inheriting only `request_engine_app`, enumerates all executable functions in `request_engine`, `request_cmd` and `request_admin`, and requires exact equality with the reviewed allowlist. The test also requires no `request_admin` schema access. Any future GRANT or function addition that expands the app surface without updating the reviewed allowlist fails release CI.

This closes the protected-function portion of G06 only. G14 remains a separate broader release gate for the complete app/worker/admin/table/function/`SECURITY DEFINER` privilege contract.

## Exit conditions

All Party-authority exit conditions are satisfied on CI #905 (`32029659776`) at head `f6cec8e2c2b779d4b18f1a12195b52b0ffa15367`:

1. the canonical capability registry and this inventory agree on every runtime-available `party_scope` surface;
2. every material exact scope above has a deterministic revoke race using production-style application transactions;
3. SlotOffer authority ordering is corrected and regression-tested;
4. cross-tenant/nonexistent and wrong-scope denial behavior remains opaque at protected public surfaces;
5. operator override is proven to come only from authenticated capability state and cannot bypass tenant boundaries;
6. the complete candidate/reverse-order/concurrency evidence bundle is `VALID`.

The exact-head artifact collected 392 tests across all 103 expected release files, passed all 392 in reverse order, passed three concurrency-stability rounds of 70 tests, passed mutation probes and executed the real-LOGIN app function allowlist. R23/R24 and G06 may therefore be `PASS` on this branch subject to the registry reconciliation itself passing canonical CI. Final V3 release promotion must regenerate this evidence after the candidate stops changing.
