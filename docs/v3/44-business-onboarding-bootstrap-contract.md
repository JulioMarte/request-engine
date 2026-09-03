# 44 — Business onboarding and bootstrap API contract

Status: normative implementation contract for `feature/business-onboarding-api`.

## 1. Goal

A newly provisioned tenant must be able to become operational through authenticated public/operator APIs without copying SQL fixtures, editing seed files, or writing directly to owner tables.

The acceptance journey is:

```text
provisioned tenant + bootstrap principal
-> create tenant business Party
-> establish root operational authority
-> create one or more Locations
-> configure Location hours/profile
-> create Catalog capabilities and Offerings/OfferingVersions
-> create Booking Resources and supply
-> create ServiceQueues when the business uses walk-in flow
-> configure communication channel policy when messaging is enabled
-> register a customer Party
-> find a real slot / join a real queue
-> create the first Reservation / QueueEntry
```

`tests/e2e/tenant_sandbox.py` may continue to use direct SQL to establish test prerequisites, but it must no longer be the only practical runbook for creating those production concepts.

## 2. Design rule: onboarding is composition, not a new authority owner

Onboarding does not introduce a generic CRUD module and does not transfer ownership.

```text
Tenancy        owns Organization/Party/Representation authority
Catalog        owns Location, Offering, OfferingVersion, ResourceCapability,
               OfferingResourceRequirement and business profile facts
Booking        owns Resource, Resource capability assignment, contextual assignment,
               recurring availability and capacity supply
Queue          owns ServiceQueue and queue policy/configuration
Communications owns channel policy and communication intent configuration
```

Every mutation is an owner command with its own capability, idempotency identity, tenant transaction, validation, audit and PostgreSQL backstop.

A convenience client may orchestrate these endpoints, but Request Engine must not hide a multi-owner mutation behind one giant transaction or a generic `POST /setup` command.

## 3. Vertical-neutral model

The API must work for clinics, barber shops, salons, veterinary practices, hardware stores and similar small businesses without introducing vertical-specific tables for the basic setup path.

Examples:

- a clinic may create Offering `cardiology_consultation`, Resource `dr_garcia`, one appointment-capable Location and optional ServiceQueue;
- a barber shop may create Offering `haircut`, Resources for individual barbers, recurring availability and a walk-in ServiceQueue;
- a hardware store may create Locations and Resources/Queues for service desks without enabling appointment booking at all.

Therefore readiness is capability-specific, not one global boolean. A tenant may be ready for `walk_in_queue` while intentionally not ready for `appointments`.

## 4. Bootstrap authority

Operational owner commands currently require a tenant Party plus exact `representations` scopes. A truly empty tenant cannot satisfy that requirement through API, so the bootstrap path must explicitly establish the root authority.

### 4.1 Provisioning assumption

Authentication/provisioning creates:

- Organization;
- initial Principal;
- trusted capability `organization.bootstrap` on that principal.

It does **not** need to seed business configuration rows.

### 4.2 Root business Party

The bootstrap principal creates the tenant's own Party with the existing:

```http
POST /v1/parties
```

using `party_kind="organization"`.

### 4.3 Operational authority grant

New semantic command:

```http
POST /v1/organization/bootstrap-operational-authority
Capability: organization.bootstrap
Idempotency-Key: required
```

Body:

```json
{
  "authority_party_id": "uuid"
}
```

The Party MUST be an active `organization` Party in the caller tenant. The command grants the initial principal the closed operational scopes required by the current product:

```text
operations.manage_profile
operations.manage_supply
operations.manage_terms
operations.manage_discovery
```

The command is bootstrap-only. It is not a general Representation management endpoint. Replay returns the same grant set. Existing incompatible root grants fail closed. Runtime integrations/bots do not receive `organization.bootstrap` by default.

## 5. Owner API surface

### 5.1 Catalog — Location

Existing owner commands are admitted into normal HTTP composition:

```http
POST  /v1/operations/locations
PATCH /v1/operations/locations/{location_id}
PUT   /v1/operations/locations/{location_id}/contacts
PUT   /v1/operations/locations/{location_id}/hours
POST  /v1/operations/locations/{location_id}/hours-exceptions
```

They remain Catalog-owned and authority-scoped.

### 5.2 Catalog — capabilities and offerings

New semantic surfaces:

```http
POST /v1/catalog/resource-capabilities
Capability: catalog.manage

POST /v1/catalog/offerings
Capability: catalog.manage
```

`POST /v1/catalog/offerings` creates one stable Offering plus its initial immutable OfferingVersion and its ordered resource requirements in one Catalog transaction.

The v1 body includes:

```text
offering_key
display_name
description?
duration_minutes
bookable
requestable
booking_policy
requirements[] = { capability_id, quantity }
```

Creating later OfferingVersions is a separate semantic command and is not required for the empty-tenant acceptance journey.

### 5.3 Booking — Resource and supply

New semantic surface:

```http
POST /v1/booking/resources
Capability: booking.configure_supply
```

The command creates one Resource, assigns declared Catalog capability ids and optionally establishes its initial Location assignment + weekly availability. It does not create an appointment or consume capacity.

Body supports:

```text
resource_key
display_name
capacity_model = exclusive | pooled
capacity_units
capability_ids[]
location_id?
weekly_availability[]
```

For v1, a resource has at most one initial Location assignment in this command. Existing contextual supply commands remain authoritative for later changes.

### 5.4 Queue — ServiceQueue

New semantic surface:

```http
POST /v1/queues
Capability: queue.configure
```

Body:

```text
queue_key
display_name
location_id
offering_id?
```

The linked Location and optional Offering must belong to the same tenant. Queue creation does not admit a customer or fabricate queue entries.

### 5.5 Communications — channel policy

New semantic surface:

```http
PUT /v1/communications/channel-policies/{purpose}
Capability: communications.configure
```

The first admitted purposes are the currently supported communication purposes in the Communications contract. The body configures the ordered channel/provider policy already consumed by dispatch/escalation code; it must validate rather than accept arbitrary JSON.

Missing policy remains distinguishable from an intentionally disabled purpose.

## 6. Readiness

New read-only composition capability:

```http
GET /v1/onboarding/readiness
Capability: onboarding.read
```

Response reports owner-backed facts and blockers, not guesses:

```json
{
  "business_party": {"ready": true},
  "locations": {"ready": true, "count": 1},
  "appointments": {
    "ready": false,
    "blockers": ["no_bookable_offering", "no_resource_supply"]
  },
  "walk_in_queue": {"ready": true, "queue_count": 1},
  "communications": {
    "ready": false,
    "blockers": ["no_channel_policy"]
  }
}
```

Readiness is advisory setup state. It never mutates owners and never substitutes for owner validation at booking/join/dispatch time.

## 7. Security and tenancy

All configuration writes:

- obtain `organization_id` and `principal_id` only from authenticated ActorContext;
- reject tenant ids in request bodies;
- require explicit operator/bootstrap capabilities;
- run under `tenant_transaction` / FORCE-RLS owner tables;
- use Idempotency-Key for every mutation;
- preserve the same-tenant foreign-key/lookup boundaries;
- never expose whether another tenant owns a conflicting key or identifier.

## 8. Idempotency and concurrency

Natural keys (`location_key`, `offering_key`, `capability_key`, `resource_key`, `queue_key`) are tenant-local uniqueness identities.

For each create command:

```text
same Idempotency-Key + same command -> same result
same Idempotency-Key + different command -> 409 idempotency_conflict
concurrent different keys + same natural key -> one winner, typed same-tenant conflict
```

The PostgreSQL unique constraint is the concurrency backstop; application pre-checks are not authority.

## 9. Acceptance proof

The feature is not complete until PostgreSQL 18 current-product evidence proves a tenant created without business configuration can, through HTTP only after authentication/provisioning:

1. create its organization Party;
2. bootstrap operational authority;
3. create Location and hours;
4. create ResourceCapability;
5. create a bookable Offering + initial version + requirement;
6. create Resource + capability assignment + initial recurring supply;
7. create ServiceQueue;
8. configure a channel policy;
9. register a patient/customer Party;
10. find a slot and book it;
11. join the configured queue;
12. obtain readiness with no appointment/queue bootstrap blockers;
13. prove another tenant cannot read/use any created id.

No step 1–12 may use direct SQL to create the business configuration under test.

## 10. Explicit non-goals

This slice does not add:

- billing, inventory or clinical records;
- arbitrary generic table CRUD;
- tenant creation/authentication itself;
- general Representation administration beyond the one bootstrap root grant;
- same-tenant Party merge;
- provider credential/secrets management;
- vertical templates that silently create configuration.

Templates/wizards may be added later as clients over these owner APIs once the primitive onboarding path is proven.