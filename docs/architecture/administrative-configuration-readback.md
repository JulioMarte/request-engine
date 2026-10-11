# Administrative configuration readback

## Purpose and ownership

Operators must be able to reconstruct configuration and its current revisions
before changing it. Admin UI, HTTP clients and projected tools use the same owner
operations; none has a private persistence path. These are Queries, not Commands.
An ID or a capability listed in a response never grants execution authority.

## Booking supply

Owner: Booking. Capability: `booking.read_supply`, operator audience. Authentication
uses the composed actor boundary and the explicit tenant selector. The database
reader additionally checks current Party authority: `operations.manage_supply`
for resources, assignments, windows and exceptions; `operations.manage_terms`
for commercial terms. Reads use one tenant transaction and tenant-filtered SQL
under the application role, with RLS as a structural backstop.

| Method/path | Returned configuration |
| --- | --- |
| GET `/v1/booking/resources` | Resource capacity, capabilities and availability revision |
| GET `/v1/operations/resource-assignments` | Location assignment, lifecycle and current revisions |
| GET `/v1/operations/context-terms` | Commercial terms and revision |
| GET `/v1/operations/resource-assignments/{assignment_id}/availability` | Local windows and resource availability revision |
| GET `/v1/operations/resource-assignments/{assignment_id}/exceptions` | Assignment exceptions and availability revision |
| GET `/v1/booking/resources/{resource_id}/exceptions` | Resource-wide exceptions and availability revision |

Stable operation IDs, in table order: `booking_resource_list`,
`booking_resource_assignment_list`, `booking_context_terms_list`,
`booking_resource_assignment_availability_list`,
`booking_resource_assignment_exception_list`, `booking_resource_exception_list`.
These Queries currently declare HTTP owner/capability metadata, not opt-in tool
audiences. Tool projection is not required for the current HTTP readback journey
and is not claimed as implemented. A later projection must delegate to these
same owner Queries with explicit audiences; it must not add a separate handler
or duplicated policy.

Each Query requires `authority_party_id`. Resource collections can filter by
`resource_id`; assignment collections additionally by `location_id` and
`assignment_id`; terms can filter by `assignment_id`. Unsupported parameters are
rejected instead of silently ignored.

Collections return `{items, next_cursor}`. `limit` defaults to 50 and is bounded
at 100. Pass the returned UUID as `after`, preserving the other filters. A
lookahead row determines continuation: an exactly full final page has no next
cursor. This is a live, UUID-ordered keyset, not a stable snapshot or chronological
ordering. Concurrent insertion can require refreshing the collection. Foreign
tenant IDs produce no configuration rows; false Party authority is denied.
An empty windows/exceptions page intentionally does not distinguish an absent
parent from a foreign-tenant parent. It also does not supply a parent revision:
clients must read the authorized resource/assignment collection before issuing
a revision-sensitive change. Do not invent revision zero for these parents.

## Communications channel policy

Owner: Communications. Capability: `communications.read_configuration`, operator
audience. GET `/v1/communications/channel-policies/{purpose}` uses
`authority_party_id`, tenant actor authentication and current
`operations.manage_profile` Party authority, matching the existing write scope.

Missing policy returns `configured=false`, `revision=0`, and null enabled/policy
fields. This explicitly tells a client to create through the existing PUT with
`expected_revision=0`; it must not invent default configuration. Existing policy
returns its current revision and channel settings. GET and PUT use separate typed
HTTP Views, not exposed application dataclasses.
The Query operation ID is `communications_channel_policy_get`; the existing
Command retains `communications_configure_channel_policy`.

## Shared guarantees and deployment

- Responses use `Cache-Control: no-store`; no credentials or delivery tokens are
  exposed by these configuration Queries.
- Queries have no idempotency key: they do not persist business changes. Subsequent
  Commands retain their own revision and idempotency policies.
- The read surfaces use existing owner facts rather than a second configuration
  model. Migration `0040_tenant_controller_v7` separately versions the explicit
  initial-controller permission manifest and governed adoption path for the new
  Queue Query capability; it does not backfill permissions.
- New capabilities are not silently appended to immutable initial-controller
  policy versions. A reviewed new default can supply them to future organizations;
  existing staff delegation can grant only capabilities already inside the
  actor's delegable ceiling. Existing v3 controllers cannot obtain these absent
  capabilities through that command or self-upgrade. Their adoption journey requires
  the governed review/consent/apply operations: see ADR 0016. OpenAPI visibility is not a grant.
- These Queries belong to the tenant runtime API, not the platform-control API.
  The admin console projects them in the tenant business configuration workspace
  through the same canonical operation catalog and executor.
- Booking monetary HTTP values use precision-preserving decimal strings. This is
  a deliberate pre-production contract adaptation, not a float conversion.

## Proof ownership

`tests/modules/booking/test_supply_configuration_http.py` and
`tests/modules/communications/test_channel_configuration_http.py` prove bounded,
typed, closed-query HTTP behavior. PostgreSQL proof belongs to
`tests/integration/f1_operational_profile/test_supply_configuration_reads.py`
in the canonical current-product lane. The database proof must run under the
restricted application role: privileged fixture setup alone is not proof of
runtime authorization. Execution status belongs to the remediation evidence log,
not this contract.

## Catalog and service-queue inventory

Catalog exposes `catalog_location_configuration_list/read` and
`catalog_offering_configuration_list/read` under `/v1/catalog`. Locations require
`catalog.read_configuration` and `operations.manage_profile` Party authority;
offerings require the same capability and `operations.manage_terms`. Readback
includes current operational/booking-policy revisions and the latest offering
version reference.

Queue exposes `queue_service_queue_configuration_list/read` under
`/v1/queues/configuration`, using the explicit `queue.read_configuration` Query
capability and `operations.manage_supply` Party authority. Inventory includes
active and inactive queues. These administrative Queries do not reuse public
active-queue discovery as proof of administration permission.

All six operations require `authority_party_id`, enforce current tenant actor
and Party authority in a restricted application-role transaction, return typed
HTTP Views, reject unsupported query fields, and use bounded keyset collection
pages. Detail reads do not expose another tenant's configuration. No business
state is written by these Queries.
