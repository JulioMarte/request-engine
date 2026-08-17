# V3 Party-authority adversarial closure inventory

Status: Phase 6I working inventory. This document freezes the runtime Party-authority surface that must be proven before R23 and the Party-authority portion of G06 may move from `PARTIAL` to `PASS`.

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

R23 is closed by proving every distinct material exact-scope authority root, not by duplicating the same race for every endpoint that shares one scope. At least one representative mutation per row below must use independent PostgreSQL/runtime transactions, deliberate overlap, and final-state/cardinality assertions.

| Exact scope | Representative material command | Existing deterministic revoke race at Phase D start | Required Phase D action |
| --- | --- | --- | --- |
| `appointments.book` | `appointments.book` | yes | retain |
| `appointments.manage` | `appointments.cancel` or `appointments.confirm_attendance` | no | add |
| `queue.join` | `queue.join` | yes | retain |
| `queue.manage` | `queue.leave` | no | add |
| `waitlist.join` | `waitlist.join` | yes | retain |
| `waitlist.manage` | `waitlist.accept_offer` / `waitlist.decline_offer` | no | add; authority must precede revision/lifecycle |
| `reminders.manage` | `reminders.cancel_plan` | no | add |
| `requests.submit` | `requests.submit` | yes | retain |
| `requests.manage` | `requests.cancel` | no | add |

A race must demonstrate both serialized winner orders:

- command establishes current authority first -> revoke/deactivation cannot pass the locked authority root until the command commits; the command may complete once;
- revoke/deactivation wins first -> the material command cannot establish authority and produces no authoritative side effect.

## Adversarial denial matrix

Each Party-scoped family must have executable coverage for the relevant cases:

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

Queries need no authority row lock because they create no material business effect, but they must still derive the target Party from authoritative tenant state and must not bypass RLS or exact-scope checks.

## Known Phase D defect at inventory freeze

`waitlist.accept_offer` and `waitlist.decline_offer` currently lock the SlotOpportunity/SlotOffer and expose revision/lifecycle checks before resolving `waitlist.manage` authority. That order contradicts the frozen mutation protocol above and can expose same-tenant SlotOffer state to a Principal that has the action capability but lacks Party authority. Phase D must move Party authority ahead of revision/status/expiry validation while preserving the canonical Opportunity -> Offer lock topology.

## Exit conditions

The Party-authority portion of G06 and R23 may move to `PASS` only when all of the following are true on one exact head:

1. the canonical capability registry and this inventory agree on every runtime-available `party_scope` surface;
2. every material exact scope above has a deterministic revoke race using production-style application transactions;
3. SlotOffer authority ordering is corrected and regression-tested;
4. cross-tenant/nonexistent and wrong-scope denial behavior remains opaque at protected public surfaces;
5. operator override is proven to come only from authenticated capability state and cannot bypass tenant boundaries;
6. the complete candidate/reverse-order/concurrency evidence bundle is `VALID`.

This inventory does not promote the separate runtime privilege gate G14. PostgreSQL role/DDL/BYPASSRLS/SECURITY DEFINER closure remains its own phase.