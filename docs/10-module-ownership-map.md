# Request Engine — module ownership map

> **Estado:** normativo para ownership del código Python. El modelo relacional sigue definido por los documentos de dominio/DBA.

This map answers: **where does a change belong?** It assigns maintenance ownership; it does not imply one Python entity/repository/endpoint per table.

## 1. Summary

| Module | Primary ownership | Key DB/read/cmd surfaces |
|---|---|---|
| `tenancy` | Organization, Principal, Party, Representation | organizations, principals, parties, representations |
| `catalog` | Offering/version/configuration/templates | offerings, offering_versions, resource_requirement_templates |
| `requests` | request intent, selection, OutcomeScope, workflow/completion | requests, participants, selections, outcome scopes, correlations; `request_read.request_summary_v1` |
| `booking` | resource/schedule/capacity/hold/reservation commitments | resources, schedules, pools, authorities/claims/holds, reservations/allocations/external commitments; booking read views and capacity primitives |
| `delivery` | admission, queue, execution, fulfillment | queue entries, service sessions, fulfillments/corrections; queue read view |
| `payments` | pricing, obligations, financial facts/application/recovery | price/payment tables, observations, allocations, refunds/disputes/reconciliation; payment read views |
| `dispatch` | field-service dispatch destination/feasibility lifecycle | dispatch/destination lineage and dispatch-specific feasibility links |
| `platform` | technical cross-cutting mechanics | DB session/UoW, idempotency, outbox, audit/events, observability, security plumbing |

## 2. Tenancy

Owns `Organization`, `Principal`, `Party`, and `Representation`, especially hard tenant boundaries and local authority snapshots/revocation coordination. Other modules consume public tenancy contracts; participant role or correlation never grants authority by implication.

Primary invariant ownership: tenant/authority invariants I01-I05 and future authority-specific extensions.

## 3. Catalog

Owns `Offering`, `OfferingVersion`, and reusable `ResourceRequirementTemplate` configuration.

Boundary:

```text
catalog ResourceRequirementTemplate
        ↓ materialization
booking CommitmentRequirement / hold requirement intent
```

Runtime reservations do not mutate catalog history to represent commitment state.

## 4. Requests

Owns `Request`, RequestParticipant/Target, ExternalCorrelation, OfferingSelection, OutcomeScope, workflow key/version, completion decision and completion-validity coordination.

Initial commands:

```text
CreateRequest
AddRequestParticipant
SelectOffering
UpdateOfferingSelectionBeforeCommitment
CompleteRequest
```

Owns `request_read.request_summary_v1`.

`OutcomeScope` belongs here as requested-outcome serialization identity; `delivery` owns Fulfillment facts applied to it. Fulfillment commands therefore coordinate through the requests public boundary and the same DB lock root required by the domain protocol.

## 5. Booking

Owns Resource/capability assignment, AvailabilitySchedule, ScheduleException, operating-location eligibility, CapacityPool/membership, CapacityAuthority, CapacityClaim, CapacityHold, planning revision mechanics, Reservation/ReservationItem, CommitmentRequirement, ResourceAllocation and external commitment dependencies.

Initial commands include:

```text
CreateCapacityHold
ReleaseCapacityHold
ConfirmReservation
CancelReservationScope
RescheduleReservation
ReplaceResourceAllocation
ChangeResourceAvailability
ChangeScheduleException
ChangeCapacityPoolMembership
```

Owns:

```text
request_read.reservation_summary_v1
request_read.external_commitment_status_v1
request_cmd.lock_capacity_authorities
request_cmd.advance_planning_revision
```

Schedules, locations, pools, claims, holds and reservations are intentionally together because they share the same reservability authority/revision and race protocols.

## 6. Delivery

Owns AdmissionScope mapping, QueueEntry/waitlist/check-in/no-show behavior, ServiceSession, Fulfillment and FulfillmentCorrection.

Initial commands:

```text
CheckIn
JoinQueue
PromoteWaitlistEntry
StartServiceSession
CompleteServiceSession
RecordFulfillment
CorrectFulfillment
```

Owns `request_read.queue_entry_status_v1`.

Reservation-backed execution uses booking public contracts. Fulfillment coordinates with requests-owned OutcomeScope. `CompleteServiceSession` never implies `CompleteRequest` automatically.

## 7. Payments

Owns PriceDetermination, PaymentRequirement, PaymentTransaction, FinancialObservation, ObservationCorrection, FinancialReversal, PaymentAllocation/Adjustment, Refund, PaymentDispute, ReconciliationCase, provider financial-event normalization and manual verification/dual control.

Initial commands include pricing/repricing, recording/correcting observations, manual verification/approval, allocation/adjustment, refund/reversal, dispute and reconciliation resolution.

Owns:

```text
request_read.payment_requirement_status_v1
request_read.payment_transaction_status_v1
```

Payments owns the financial truth Request Engine needs, not generic accounting, tax, PSP settlement, or fulfillment truth.

## 8. Dispatch

Owns `Dispatch`, material Destination lineage and field-service feasibility semantics. `ChangeDispatchDestination` belongs here.

Booking owns shared capacity authorities and PlanningRevision mechanics. A dispatch feasibility provider adapter may live in dispatch, but committing capacity still goes through booking's public authority boundary.

## 9. Platform

Platform is not a business module.

- `platform/db`: engine/session factories, transaction/UoW plumbing, PostgreSQL error translation and technical DB types.
- `platform/idempotency`: wrappers/contracts for `request_cmd.acquire_idempotency` and `complete_idempotency`.
- `platform/outbox`: claim/delivery lease infrastructure for outbox command primitives. Business payload production remains with the emitting command.
- `platform/audit` / `platform/events`: cross-cutting append mechanics and serialization contracts, not module policy.
- `platform/security`: authentication/Principal plumbing and common technical enforcement helpers. Representation/domain authority remains tenancy/application policy.

## 10. Cross-module transaction examples

`ConfirmReservation` is owned by booking and may read/lock request/selection state through requests contracts while committing booking state in one transaction.

`CorrectFulfillment` is owned by delivery but coordinates OutcomeScope + Request completion boundary + correction fact in the serialization order required by the domain contract.

`RepriceCommittedScope` is owned by payments and may reference Request/OfferingSelection contracts while preserving immutable financial history.

## 11. Ownership change gate

Moving a concept between top-level modules or adding a module requires updating this map, affected module READMEs, import-boundary tests, DB/read/cmd ownership mapping and preferably an ADR for material/hard-to-reverse decisions.

Never infer automatically:

```text
table → domain entity → repository → endpoint
```

Some tables exist as serialization identities, relational links, append facts, or DB integrity structures rather than public domain/API objects.
