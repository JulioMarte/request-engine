# 44 — Business onboarding and bootstrap API contract

Status: normative implementation contract for the business-onboarding API
surface. This document describes what is implemented on
`feature/business-onboarding-api`; the reference acceptance proof is
`tests/e2e/test_onboarding_journey.py`.

## 1. Goal

A newly provisioned tenant must be able to become operational through
authenticated public/operator APIs without copying SQL fixtures, editing seed
files, or writing directly to owner tables.

The acceptance journey is:

```text
provisioned tenant + bootstrap principal
-> create tenant business Party
-> establish root operational authority
-> create one or more Locations
-> configure Location hours (+ optional exceptions / declared holidays)
-> create Catalog capabilities and Offerings/OfferingVersions
-> set an OfferingVersion booking policy (optional override)
-> create Booking Resources with optional weekly availability
-> create ServiceQueues when the business uses walk-in flow
-> configure communication channel policies
-> register a customer Party
-> find a real slot / book a real Reservation
-> join the configured queue as a walk-in
-> obtain readiness with no blockers
```

`tests/e2e/tenant_sandbox.py` may continue to use direct SQL to establish test
prerequisites, but it is no longer the only practical runbook for creating
those production concepts.

## 2. Design rule: onboarding is composition, not a new authority owner

Onboarding does not introduce a generic CRUD module and does not transfer
ownership.

```text
Tenancy        owns Organization/Party/Representation authority
Catalog        owns Location, Offering, OfferingVersion, ResourceCapability,
               OfferingResourceRequirement and business profile facts
Booking        owns Resource, capability assignment, contextual assignment,
               recurring availability and capacity supply
Queue          owns ServiceQueue and queue configuration
Communications owns channel policy and communication intent configuration
```

Every mutation is an owner command with its own capability, idempotency
identity, tenant transaction, validation, audit and PostgreSQL backstop. A
convenience client orchestrates these endpoints; Request Engine never hides a
multi-owner mutation behind one giant transaction or a generic `POST /setup`.

## 3. Vertical-neutral model

The API works for clinics, barber shops, salons, veterinary practices,
hardware stores and similar small businesses without vertical-specific tables.
Readiness is capability-specific, not one global boolean: a tenant may be
ready for `walk_in_queue` while intentionally not ready for `appointments`.

## 4. Bootstrap authority

### 4.1 Provisioning assumption

Authentication/provisioning creates:

- Organization;
- initial Principal;
- trusted capability `organization.bootstrap` on that principal.

It does **not** seed business configuration rows.

### 4.2 Root business Party

The bootstrap principal creates the tenant's own Party through the existing
`parties.register` surface:

```http
POST /v1/parties
Capability: parties.register
```

with `party_kind="organization"`. Customer/subject Parties are registered the
same way with `party_kind="person"`.

### 4.3 Operational authority grant

```http
POST /v1/organization/bootstrap-operational-authority
Capability: organization.bootstrap
Idempotency-Key: required
```

Body: `{"authority_party_id": "uuid"}`.

The Party MUST be an active `organization` Party in the caller tenant
(otherwise `404 tenant_reference_not_usable`). The command grants the calling
principal the closed operational scope set:

```text
operations.manage_profile
operations.manage_supply
operations.manage_terms
operations.manage_discovery
```

as `delegated`, active Representations on the authority Party with no expiry.
Replay with the same Idempotency-Key returns the same grant set. Existing
active non-delegated grants for those scopes fail closed. This is a
bootstrap-only root grant, not a general Representation administration
endpoint; runtime integrations/bots do not receive `organization.bootstrap` by
default.

## 5. Capability → endpoint map

The onboarding surface is composed of these public capabilities:

| Capability                  | Endpoints                                                                                       |
| --------------------------- | ----------------------------------------------------------------------------------------------- |
| `organization.bootstrap`    | `POST /v1/organization/bootstrap-operational-authority`                                           |
| `catalog.manage`            | `POST /v1/catalog/resource-capabilities`, `POST /v1/catalog/offerings`, `PUT /v1/catalog/offerings/{offering_version_id}/booking-policy` |
| `booking.manage_supply`     | `POST /v1/booking/resources` (reuses the existing supply capability; there is no `booking.configure_supply`) |
| `queue.configure`           | `POST /v1/queues`                                                                                |
| `communications.configure`  | `PUT /v1/communications/channel-policies/{purpose}`                                              |
| `onboarding.read`           | `GET /v1/onboarding/readiness`                                                                   |

All of these run on the public application. The operational authority granted
by the bootstrap additionally unlocks the operator-only configuration
application (`operations.manage_*` Representations):

```text
POST  /v1/operations/locations                                   profile scope
PATCH /v1/operations/locations/{location_id}                     profile scope
PUT   /v1/operations/locations/{location_id}/contacts            profile scope
PUT   /v1/operations/locations/{location_id}/hours               profile scope
PUT   /v1/operations/locations/{location_id}/hours-exceptions    profile scope
PUT   /v1/operations/organization/holidays                       profile scope
PUT   /v1/operations/offering-versions/{id}/booking-terms        terms scope
POST  /v1/operations/resource-assignments                        supply scope
POST  /v1/operations/resource-assignments/{id}/retire            supply scope
PUT   /v1/operations/resource-assignments/{id}/availability      supply scope
PUT   /v1/operations/resource-assignments/{id}/exceptions        supply scope
PUT   /v1/operations/resources/{resource_id}/exceptions          supply scope
POST  /v1/operations/context-terms                               terms scope
POST  /v1/operations/context-terms/{id}/supersede                terms scope
```

Every request carries `authority_party_id`; the command resolves the exact
`operations.manage_*` Representation inside its authoritative transaction.

## 6. Owner API semantics

### 6.1 Catalog — capabilities and offerings

`POST /v1/catalog/resource-capabilities` (`catalog.manage`, `operations.manage_profile`
authority) creates one tenant-local `ResourceCapability` with a tenant-unique
`capability_key`.

`POST /v1/catalog/offerings` (`catalog.manage`, `operations.manage_terms`
authority) creates one stable Offering plus its initial immutable
OfferingVersion (version 1) and its ordered resource requirements in one
Catalog transaction:

```text
offering_key
display_name
description?
duration_minutes
bookable
requestable
slot_step_minutes
requirements[] = { capability_id, quantity }
reservation_policy (bootstrap booking policy)
```

Creating later OfferingVersions is a separate concern and is not required for
the empty-tenant acceptance journey.

### 6.2 Booking policy — append-only override ledger

```http
PUT /v1/catalog/offerings/{offering_version_id}/booking-policy
Capability: catalog.manage
Authority: operations.manage_terms
```

Body:

```json
{
  "authority_party_id": "uuid",
  "expected_revision": 0,
  "booking_policy": {
    "slot_step_minutes": 15,
    "attendance": {"no_show_after_minutes": 20},
    "communications": {"confirmation": false},
    "slot_recovery": {"enabled": false}
  }
}
```

Persistence is `request_engine.offering_version_booking_policies`
(migration `0033_offering_booking_policy`), an append-only ledger:

- the effective booking policy of an OfferingVersion is the highest-revision
  ledger row, or `offering_versions.booking_policy` while no row exists;
- `expected_revision` is the current highest revision (`0` = bootstrap policy
  still in force); a stale value is a typed revision conflict;
- the command appends revision `current + 1`; UPDATE/DELETE on the ledger are
  rejected by a PostgreSQL trigger for every role, including the table owner;
- the revision is serialized by locking the latest ledger row before the
  insert; a concurrent winner produces a typed conflict, never a lost append;
- new Reservations freeze the effective policy into
  `reservations.booking_policy_snapshot`; Reservations that already exist keep
  their frozen snapshot untouched.

### 6.3 Booking — Resource and initial supply

```http
POST /v1/booking/resources
Capability: booking.manage_supply
Authority: operations.manage_supply
```

`location_id` is required. Body:

```text
authority_party_id
location_id                    (required, active, same tenant)
resource_key
display_name
capacity_model = exclusive | units   (default exclusive; no pooled baseline)
capacity_units                 (>= 1, default 1)
capability_ids[]               (optional; all must be same-tenant)
weekly_availability[]          (optional)
```

`weekly_availability` windows:

```text
weekday      0..6 (0 = Monday)
local_start  local wall-clock time
local_end    local wall-clock time
valid_from   optional date
valid_until  optional date
```

When `weekly_availability` is provided, the command creates one Resource, the
capability assignments, one open-ended `resource_location_assignments` row on
the given Location and the weekly windows, and reports the final resource
`availability_revision` and `resource_location_assignment_id`. Without
windows, the Resource is created without an assignment; supply is configured
later through `/v1/operations/resource-assignments`. The command never
creates an appointment or consumes capacity.

### 6.4 Queue — ServiceQueue

```http
POST /v1/queues
Capability: queue.configure
Authority: operations.manage_supply
```

Body: `queue_key`, `display_name`, `location_id` (required), `offering_id`
(optional). The linked Location and optional Offering must belong to the same
tenant. Queue creation does not admit a customer or fabricate queue entries.
Queue selection is FIFO only (`service_queues.policy_key` is DB-constrained to
`'fifo'`).

### 6.5 Communications — organization channel policies

```http
PUT /v1/communications/channel-policies/{purpose}
Capability: communications.configure
Authority: operations.manage_profile
```

`purpose` is the closed vocabulary of purposes Communications actually creates
today:

```text
appointment_confirmation
appointment_reminder
attendance_confirmation_request
slot_offer_available
operational_recovery_impact
operational_recovery_rescheduled
```

Body: `enabled`, ordered `channels` (subset of
`email|phone|sms|voice|whatsapp`), optional `provider_key`,
`reconcile_after_seconds` and `retry_after_seconds` (30..86400), and
`expected_revision` (a new row requires `0`; a stale value is `409
revision_conflict`).

Persistence is `request_engine.organization_channel_policies` (migration
`0034_org_channel_policies`), one row per organization + purpose. Resolution
precedence at dispatch:

```text
task-level channel_policy (anything not the hardcoded patient-transactional
default sentinel)
  > enabled organization policy row for the task purpose
  > hardcoded patient-transactional default
```

Missing policy remains distinguishable from an intentionally disabled purpose:

- absent row → not configured; resolution falls back to the default;
- present with `enabled = false` → the CREATION of new intents for that
  purpose is rejected with the typed `channel_purpose_disabled` conflict,
  while tasks already in flight keep their own frozen `channel_policy`
  snapshot and are not touched (including dispatch of tasks that froze the
  default sentinel);
- present with `enabled = true` → the organization configuration serves as
  the default when a task does not bring its own policy.

### 6.6 Holidays — organization closure days

```http
PUT /v1/operations/organization/holidays
Authority: operations.manage_profile
```

Body: `holidays[] = { date, reason? }`. The command requires at least one
active Location and materializes each declared date as one full-day
`unavailable` `location_hours_exceptions` row per active Location, expressed
in that Location's timezone. Re-declaring the same date is idempotent
(already-declared days are counted and reported); a declared holiday that
would overlap a different active exception is a typed conflict.

Holidays are explicitly declared dates; there is no recurring national
calendar (see §11).

## 7. Readiness

```http
GET /v1/onboarding/readiness
Capability: onboarding.read
```

Response reports owner-backed facts, not guesses:

```json
{
  "business_party": {"ready": true},
  "locations": {"ready": true, "count": 1},
  "appointments": {"ready": true, "blockers": []},
  "walk_in_queue": {"ready": true, "queue_count": 1},
  "communications": {"ready": true, "blockers": []}
}
```

Facts come from each owning module through its published contracts surface:

- `business_party` — Tenancy: an active `organization` Party exists;
- `locations` — Catalog active Location count;
- `appointments` — blockers `no_bookable_offering` (no bookable
  OfferingVersion) and `no_resource_supply` (no Resource supply with recurring
  availability);
- `walk_in_queue` — at least one active ServiceQueue exists;
- `communications` — ready by default (the hardcoded patient-transactional
  policy applies when nothing is configured); the only blocker is
  `channel_purpose_disabled`, present while any purpose is intentionally
  disabled.

Readiness is advisory setup state. It never mutates owners and never
substitutes for owner validation at booking/join/dispatch time.

## 8. Last mile: public surface is unchanged

Onboarding composes into the existing public capabilities. Slot discovery and
booking use `appointments.find_slots` / `appointments.book` with the subject
authority model already enforced there (exact Representation scope or explicit
`appointments.subject_override`); walk-in admission uses `queue.join`
(`queue.join` scope or `queue.subject_override`). The operator application
that bootstrapped the organization books and admits customers through these
same public endpoints; no onboarding-specific booking path exists.

## 9. Security and tenancy

All configuration writes:

- obtain `organization_id` and `principal_id` only from authenticated
  ActorContext;
- reject tenant ids in request bodies;
- require the explicit capability AND the exact `operations.manage_*`
  Representation for the command's scope;
- run under `tenant_transaction` / FORCE-RLS owner tables;
- use Idempotency-Key for every mutation;
- never expose whether another tenant owns a conflicting key or identifier.

## 10. Idempotency and concurrency

Natural keys (`location_key`, `offering_key`, `capability_key`,
`resource_key`, `queue_key`) are tenant-local uniqueness identities.

For each create command:

```text
same Idempotency-Key + same command -> same result
same Idempotency-Key + different command -> 409 idempotency_conflict
concurrent different keys + same natural key -> one winner, typed same-tenant conflict
```

The PostgreSQL unique constraint is the concurrency backstop; application
pre-checks are not authority. Booking-policy revisions serialize on the latest
ledger row (§6.2).

## 11. Acceptance proof

`tests/e2e/test_onboarding_journey.py` is the reference acceptance proof. It
proves on PostgreSQL 18 that a tenant created without business configuration
(only Organization + Principal rows) can, through HTTP only:

1. create its organization Party;
2. bootstrap operational authority (replay returns the same grant);
3. create a Location, set weekly operating hours and declare an organization
   holiday;
4. create a ResourceCapability;
5. create a bookable Offering + initial version + requirement;
6. append a booking-policy override (`no_show_after_minutes`,
   `slot_step_minutes`) and prove the ledger row is append-only and that new
   slots/reservations use the override while the ledger rejects UPDATE;
7. create a Resource + capability assignment + initial weekly supply
   (exclusive capacity);
8. create a ServiceQueue;
9. configure a channel policy, prove the optimistic-revision rejection, and
   prove an intentionally disabled purpose surfaces as the typed readiness
   blocker until re-enabled;
10. register a customer Party;
11. find real slots (proving the 15-minute step from the policy override and
    that the declared holiday day yields no slots) and book one;
12. join the configured queue as a walk-in;
13. obtain readiness with no blockers.

No step 1–13 uses direct SQL to create the business configuration under test;
direct SQL is used only to inspect durable owner tables (report oracle) and to
prove the append-only ledger backstop. Readiness transitions are observed at
five checkpoints: empty world → after bootstrap + location → after offering +
resource (appointments ready) → after queue (walk-in ready) → fully ready
without blockers. Cross-tenant isolation of these endpoints is owned by the
dedicated isolation evidence and deliberately not duplicated here.

## 12. Deferred / follow-up

Explicitly NOT implemented by this surface; each item needs its own accepted
design before exposure:

- **Resource capacity update with active claims.** No command changes
  `capacity_model`/`capacity_units` of an existing Resource. Supply evolution
  today happens through assignments, weekly availability and schedule
  exceptions; capacity mutation under live CapacityClaims requires
  reconciliation semantics first.
- **SlotOffer TTL configuration.** The waitlist offer TTL is a hardcoded 300s
  default in the released-slot recovery machinery; it is not yet an
  organization- or tenant-level configuration.
- **Queue selection policies other than FIFO.** `service_queues.policy_key`
  is DB-constrained to `'fifo'`; no weighted/priority/triage ordering policy
  can be configured through `POST /v1/queues`.
- **HTTP route for intake control.** Operational intake control is only
  reachable through the operational-copilot surface; there is no direct
  `/v1/operations` intake route.
- **Pooled capacity.** Baseline capacity models are `exclusive` and `units`
  only; CapacityPool remains out of baseline.
- **Recurring national holiday calendar.** Holidays are manually declared
  dates per organization; there is no recurring rule engine and no
  pre-seeded national calendar.
- **Free-form reminder plan purposes.** `reminders.create_plan` accepts
  free-form `purpose` strings, but organization channel policies only govern
  the six closed purposes above; reminder plans with other purposes cannot be
  governed by an organization policy today.

## 13. Explicit non-goals

This slice does not add:

- billing, inventory or clinical records;
- arbitrary generic table CRUD;
- tenant creation/authentication itself;
- general Representation administration beyond the one bootstrap root grant;
- same-tenant Party merge;
- provider credential/secrets management;
- vertical templates that silently create configuration.

Templates/wizards may be added later as clients over these owner APIs once
the primitive onboarding path is proven.
