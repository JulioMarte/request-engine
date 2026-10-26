# Catalog module

> **V3 baseline module.**

Owns structured operational configuration that describes **what the business offers** and the stable vocabulary needed to plan local bookings:

```text
Location
Offering
OfferingVersion
ResourceCapability
OfferingResourceRequirement
structured business-profile/public-hours configuration where authoritative
```

`OfferingVersion` becomes immutable once referenced by authoritative state. Appointment-relevant configuration such as duration, bookable locations, resource requirements and policy/version references belongs to the exact version used by booking.

A baseline `OfferingResourceRequirement` is deliberately simple:

```text
one mandatory requirement
→ one ResourceCapability
→ one concrete Resource selected by booking
→ quantity units consumed for the appointment interval
```

Multiple requirement rows are ANDed. V3 baseline does not support OR/k-of-n requirement expressions, reusable requirement-template graphs, capacity pools or late binding optimizers.

### Decision: no `ResourceRequirementTemplate` baseline

The earlier reusable-template abstraction is unnecessary for the first verticals. Requirements are immutable children/configuration of an `OfferingVersion`. Extract a reusable template later only if multiple OfferingVersions demonstrably share an independently managed requirement definition.

Booking owns concrete `Resource`, availability, capacity claims/holds and Reservations. Catalog never owns runtime capacity commitment state.

Expected queries include:

```text
GetBusinessInfo
SearchOfferings
GetOfferingDetails
GetLocations
```

## Onboarding and bootstrap surfaces (docs/v3/44)

Catalog exposes its owner commands for empty-tenant onboarding without a new
authority owner:

- `POST /v1/catalog/resource-capabilities` and `POST /v1/catalog/offerings`
  (`catalog.manage`) create the capability vocabulary and one Offering plus
  its initial immutable OfferingVersion and requirements in one transaction;
- `PUT /v1/catalog/offerings/{id}/booking-policy` (`catalog.manage`) appends
  an override revision to the append-only
  `offering_version_booking_policies` ledger (migration 0033). The effective
  policy is the highest-revision row or the bootstrap
  `offering_versions.booking_policy`; UPDATE/DELETE are rejected by trigger;
  existing Reservations keep their frozen snapshot;
- the operational location/hours/exception surfaces plus
  `PUT /v1/operations/organization/holidays`, which materializes each declared
  date as one full-day `unavailable` hours exception per active Location in
  its timezone;
- `read_catalog_supply` (via `contracts/onboarding.py`) backs the
  `locations`/`no_bookable_offering` facts of `GET /v1/onboarding/readiness`.
  It counts active Locations and, for each active Offering, only its latest
  version if bookable. Historical bookable versions and inactive Offerings do
  not establish current readiness. This is structural configuration, not proof
  of Resource eligibility, available slots or an atomic cross-module snapshot.

Catalog provides structured operational truth for agents/applications; it is not a universal CMS or RAG system.

## API coherence and bounded discovery (2026-10-03)

Catalog schedule input admission (2026-10-06): location weekly hours reject
unknown fields, weekdays outside 0..6, offset-bearing local times, reversed
windows/date bounds and duplicate windows. Owner Commands use
`CatalogInvalidInput` (422), including direct adapter callers. Missing and
foreign location targets receive the same existing configuration conflict (409),
not an internal persistence exception; rejected commands leave no receipt,
schedule, audit or outbox fact. This does not broaden transaction-time authority
or change legacy receipt replay policy.

Base commercial terms accept finite nonnegative exact Decimal values with at
most 14 integer digits and six significant fractional places, matching
`numeric(20,6)`, plus an ASCII uppercase three-letter currency. Excess precision
is rejected (422), never silently rounded. Trailing zeroes that do not change
the value are allowed. Decimal representation exponents must stay within
PostgreSQL numeric's -16383..131071 range, including zero: extreme zero exponents
are invalid input rather than a database binding failure. HTTP amounts remain
exact decimal JSON strings; clients
must parse with decimal arithmetic. Storage and receipt values therefore agree.
Pre-production transport ADAPT (2026-10-06): input admits decimal strings and
JSON integers; fractional JSON numbers are rejected (422), even `1.0`, because
the JSON parser turns them into lossy binary floats before validation. Booleans
are not amounts. Native Decimal values remain supported for typed Python callers.
OpenAPI describes `string|integer`, not `number`; existing clients must quote
fractional prices (for example `"19.90"`).
No baseline rewrite, new grant, route or migration is required.

Offering-version booking-policy admission (2026-10-06): current `catalog.manage`,
active authority Party and exact `operations.manage_terms` Representation are
checked inside the owner transaction before idempotency, including receipt replay.
An admitted Command can finish before a later withdrawal; later new/replayed work
is denied. Principal SHARE -> Party SHARE -> committed Representation read avoids
the Representation revision trigger's lock inversion. Offering lock/CAS and the
append-only policy ledger remain unchanged; existing Reservation snapshots are
not rewritten. No automatic grants, DDL or provider I/O. This explicit
pre-production strengthening does not retrofit other Catalog Commands or
universally linearize sessions, delegation and agent policy. See
`docs/architecture/administrative-transaction-authority.md` for the scoped contract.

Owner: Catalog. Existing operation IDs/capabilities remain unchanged; bootstrap
commands remain idempotent and authority-backed, with no new tool projection.
Bootstrap ResourceCapability/Offering/policy responses have explicit transport
Views (IDs, version/revision and policy), separate from application state.
Caller-input failures from these commands use `CatalogInvalidInput`, mapped to
422 `invalid_catalog_input` / `fix_request`; internal `ValueError` is not swallowed.

`GET /v1/catalog/offerings` is a read-only, tenant-scoped Query using
`catalog.search_offerings`. Its pre-production array contract is deliberately
replaced with `{items, next_cursor}`. Page size remains 1..200, default 50;
ordering is `(display_name, id)` ascending. The reader probes one extra row,
so an exact-size terminal page has no cursor. Cursors carry ordering position
and a filter/tenant binding; they are not authorization and are revalidated
against the current trusted ActorContext. Unknown filters and malformed or
incompatible cursors fail 422. Optional `effective_at` must have a timezone;
an implicit location observation time is frozen across pages. This is keyset
continuation, not a transaction-spanning snapshot: concurrent renames/inserts
may change subsequent observations. In-repository HTTP consumers migrate together.

Location eligibility checks one active, effectively assigned Resource per
requirement: exclusive supports quantity 1; units supports quantity up to its
configured capacity. Two exclusive Resources do not satisfy one quantity-2
requirement. Multiple requirements are ANDed independently; shared-resource
competition, schedules and existing commitments are not solved here. Catalog
eligibility is structural advisory information, never a promise of availability;
Booking still selects concrete Resources and validates aggregate units under locks.
No schema migration or additional DB authority is needed for these read changes.

Administrative reconstruction uses the explicit Query capability
`catalog.read_configuration` (operator, no idempotency/revision requirement).
It must be explicitly granted; neither visibility nor `catalog.manage` silently
grants it. `GET /v1/catalog/resource-capabilities`
(`catalog_resource_capabilities_list`) returns bounded `{items,next_cursor}`
ordered by capability UUID. `GET /v1/catalog/offering-versions/{id}/configuration`
(`catalog_offering_version_configuration_read`) reads the exact immutable version,
requirements and effective booking-policy revision (0 means bootstrap policy).
Both return typed owner projections with `Cache-Control: no-store`; foreign or
absent versions are 404. Caller filters cannot select tenant/principal. Reads
authorize trusted ActorContext, use tenant transactions and existing RLS; no
cross-module dependency, provider I/O or writes are introduced. These queries
do not yet expose a full catalog version/lifecycle administration suite.

Administrative inventory also exposes Locations and Offerings, including inactive
configuration, through `catalog_location_configuration_list/read` and
`catalog_offering_configuration_list/read`. GET `/v1/catalog/locations/configuration`
and `/v1/catalog/offerings/configuration` return `{items,next_cursor}` ordered by
UUID with `limit` 1..100 (default 50) and `after` continuation. Exact reads use
`/{location_id}/configuration` or `/{offering_id}/configuration`. Every call
requires `catalog.read_configuration`, current tenant principal standing and the
exact represented `authority_party_id` inside the restricted runtime transaction:
Locations require `operations.manage_profile`; Offerings require
`operations.manage_terms`. Foreign and absent exact targets are both 404.
Location rows expose the current operational revision and profile; Offering rows
identify only the latest immutable version and its effective booking-policy
revision. They do not enumerate historical versions or grant authority over the
returned IDs. Unsupported filters fail 422. This is a live inventory, not a
transaction-spanning snapshot, and creates no business facts or grants.


Location detail also supplies required `hours_windows` and `public_contacts`
arrays from the same SQL snapshot as the profile and operational revision.
These are complete current replacement inputs: all active windows, preserving
nullable dates even for past/future validity, and active public contacts with
canonical `value` and nullable label. Superseded inactive rows are excluded;
observed empty arrays remain valid. Collection inventory does not load/project
these children. Existing `catalog.read_configuration` plus exact Party profile
authority, restricted application SELECT and tenant RLS remain unchanged.
See `docs/architecture/administrative-configuration-readback.md` for the guided
replacement and PostgreSQL proof contract.

## Configuration edits after creation (2026-10-25)

Guarantee `INV-CATALOG-CONFIG-EDITS-001`, migration `0004_configuration_edits`.
All commands require `catalog.manage`, an `Idempotency-Key`, and exact Party
authority checked inside the owner transaction before idempotency (profile scope
for Locations, terms scope for Offerings). Each new command appends audit plus a PII-free
outbox fact (ids/revisions/counts only). The change feed (ADR 0020) has no
configuration topic, so these facts are not streamed; clients re-read owner
reads after their own command response.

- **Location rename**: `catalog_location_update` accepts optional `display_name`
  (null keeps the current label). A label is not booking-material and does not
  advance `operational_revision`; the existing command keeps its audit-only effect (no outbox fact).
- **Offering rename**: `PATCH /v1/operations/offerings/{offering_id}`
  (`catalog_offering_update`). Compare-and-set on the new `offerings.revision`
  (exposed by `catalog_offering_configuration_list/read`); stale -> 409
  `offering_revision_conflict`. No OfferingVersion is created; Reservations are
  untouched.
- **Duration / base price change**: `POST /v1/operations/offerings/{offering_id}/versions`
  (`catalog_offering_version_supersede`). OfferingVersions and their base terms
  stay immutable, so a change appends version N+1 under the Offering row lock
  (the same root as base-terms insertion and contextual booking) only when
  `expected_current_offering_version_id` is still the latest; otherwise 409
  `offering_version_superseded`. Requirements, bookable/requestable flags,
  delivery policy and the *effective* booking policy (latest ledger revision or
  bootstrap) are copied; the base price is copied unless `booking_terms` is given.
  A no-op change is 422. Existing Reservations, Holds, waitlist entries and slot
  opportunities keep their exact old version. Known limits: Booking-owned
  per-assignment `booking_context_terms` are bound to the exact version and are
  not carried over (configure them for the new version); a superseded version is
  still bookable by explicit id on staff paths (catalog search, admin reads and
  discovery expose only the latest version, so clients must use
  `latest_version.id`).
- **Hours exceptions and holidays**: `GET /v1/catalog/locations/{location_id}/hours-exceptions`
  (`catalog_location_hours_exception_list`, `catalog.read_configuration` +
  exact profile authority, `include_inactive`, UUID keyset) returns ids and the
  current `operational_revision`. Removal is soft:
  `POST /v1/operations/locations/{location_id}/hours-exceptions/{exception_id}:deactivate`
  (`catalog_location_hours_exception_deactivate`) under the Location lock and
  `expected_operational_revision` CAS (the child trigger advances the revision);
  already-inactive -> 409. `POST /v1/operations/organization/holidays:remove`
  (`catalog_organization_holidays_remove`) locks every Location of the tenant in
  id order and deactivates only active `unavailable` exceptions that exactly
  cover each given local day; unmatched dates are reported in `dates_not_found`.
  Rows are never deleted.
