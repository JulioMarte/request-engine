# Administrative setup capability audit

Status: **current Stage C/D migration inventory**, subordinate to `docs/16-canonical-operation-and-tool-projection-pattern.md`, `docs/15-api-design-and-usability-standards.md` and the owning module contracts.

## 1. Product question

Can an authorized employee/admin UX or agent configure enough owner-backed Request Engine state to make the supported business journeys operational, while an unprivileged/public caller remains unable to perform those mutations?

The required security model is deliberately layered:

```text
authenticated ActorContext
        +
operation capability
        +
exact Party/Representation/resource authority where applicable
        +
owner validation
        +
idempotency/revision/concurrency rules
```

Tool discovery is an additional exposure control, not the security boundary.

## 2. Current setup/readiness facts

`onboarding.read` currently composes these owner facts:

```text
business Party exists
a Location exists
a bookable OfferingVersion exists
Booking resource supply exists
an active ServiceQueue exists
required communication purposes are enabled
```

Stage D now normalizes missing facts as machine-readable blockers:

```text
code
owner
resolution_capabilities
```

Examples:

```text
location_missing
  owner = catalog
  resolution_capabilities = [catalog.manage]

no_resource_supply
  owner = booking
  resolution_capabilities = [booking.manage_supply]

service_queue_missing
  owner = queue
  resolution_capabilities = [queue.configure]
```

The blockers deliberately do **not** hardcode owner HTTP `operationId`s. Onboarding owns readiness semantics, not the HTTP operation namespace of Catalog/Booking/Queue/etc. Stage E can map a blocker's resolution capability to the concrete operations currently mounted, visible and authorized for an ActorContext.

`business_party_missing` currently has no resolution capability. This is intentional: Stage C has not yet proved a supported owner operation that creates the tenant business Party from a fresh state. `organization.bootstrap` establishes authority over an existing authoritative Party; it must not be falsely advertised as creating that Party.

## 3. Resolution matrix

| Setup/readiness fact | Owner | Canonical operation(s) now available | Capability | Contextual authority | Status |
|---|---|---|---|---|---|
| establish initial operational authority | tenancy | `tenancy_operational_authority_bootstrap` | `organization.bootstrap` | bootstrap-specific Tenancy validation | READY |
| update Organization operational profile/contacts | tenancy | `tenancy_organization_profile_update`, `tenancy_organization_contacts_replace` | `organization.manage_profile` | exact operational Representation scope | READY |
| create/update Location profile | catalog | `catalog_location_create`, `catalog_location_update`, `catalog_location_contacts_update` | `catalog.manage` | exact operational Representation scope validated by Catalog | READY |
| configure Location hours/exceptions | catalog | `catalog_location_hours_replace`, `catalog_location_hours_exception_upsert` | `catalog.manage` | exact operational Representation scope + revision | READY |
| create Resource capability vocabulary | catalog | `catalog_manage_resource_capabilities` | `catalog.manage` | owner authority validation | READY |
| create Offering | catalog | `catalog_manage_offerings` | `catalog.manage` | owner authority validation | READY |
| configure Offering booking policy/terms | catalog | `catalog_manage_offering_version_booking_policy`, `catalog_offering_booking_terms_configure` | `catalog.manage` | owner authority + revision where applicable | READY |
| create Resource | booking | `booking_resource_create` | `booking.manage_supply` | Booking supply authority | READY |
| assign Resource to Location | booking | `booking_resource_assignment_create` | `booking.manage_supply` | Booking supply authority + revisions | READY |
| configure assignment availability | booking | `booking_resource_assignment_availability_replace` | `booking.manage_supply` | Booking supply authority + revision | READY |
| retire assignment | booking | `booking_resource_assignment_retire` | `booking.manage_supply` | Booking supply authority + revisions | READY |
| create ServiceQueue | queue | `queue_service_queue_create` | `queue.configure` | Queue owner authority validation | READY |
| configure communication purpose/channel policy | communications | `communications_configure_channel_policy` | `communications.configure` | Communications owner authority + revision | READY |
| read setup readiness | onboarding | `onboarding_read` | `onboarding.read` | organization-scoped read | READY |
| create tenant business Party from fresh state | tenancy | not yet proven | not yet proven | must establish authoritative tenant ownership safely | BLOCKER |
| manage employee Representation/capability grants | tenancy | not yet found/proven | not yet designed | revocable least-privilege delegated authority | BLOCKER |

`READY` means an owner-backed operation exists; it does **not** mean the whole administrative UX/tool journey is complete or polished.

## 4. Important architecture finding: two HTTP trust surfaces

Request Engine currently has:

```text
public HTTP app
operations/control-plane HTTP app
```

Several onboarding configuration operations are still mounted on the public HTTP process but require OPERATOR capabilities and owner authority. Other operational configuration operations, such as detailed Location/assignment scheduling, are mounted on the operations process.

This is not automatically an authorization defect: capability/Representation checks remain mandatory regardless of network surface.

However, it creates consumer-surface ambiguity. The target model is:

```text
canonical owner operation
        |
        +-> mounted HTTP surfaces justified by deployment/trust needs
        +-> authorized operation/tool catalog filtered for the ActorContext
```

Do **not** treat the public app's OpenAPI document as the tool list for a public patient agent. A public tool catalog must exclude operator/admin operations even if those HTTP routes are technically mounted on the same process.

Moving an existing route between processes is a controlled transport migration, not required merely for cosmetic purity. Authorization remains the primary control; process separation is defense in depth.

## 5. Capability vs Representation authority

Current coarse capabilities are intentionally broader than individual operation IDs.

Examples:

```text
organization.manage_profile
catalog.manage
booking.manage_supply
queue.configure
communications.configure
```

The operation identity and permission identity are therefore different.

For many administrative commands, the capability means:

> this Principal may attempt this family of operations

while the exact Party/Representation scope means:

> this Principal may perform this operation under this authority anchor/context

Both must remain enforceable.

`organization.bootstrap` and `organization.manage_profile` are intentionally separate. Initial authority establishment is a different grant decision from ongoing Organization profile/contact maintenance.

### Do not prematurely create role-shaped capabilities

Do not add `receptionist`, `manager`, `doctor`, `owner` capability keys. Roles/personas are deployment/business-policy groupings of stable capabilities.

Split a coarse capability only when two operations have demonstrably different grant requirements. For example, if a receptionist may configure Queue intake but must never alter Organization holidays or commercial terms, that is evidence for capability refinement. A desire for prettier operation IDs is not.

## 6. Capability-description drift fixed in Stage C

`catalog.manage` and `booking.manage_supply` previously described only older narrow onboarding/one-day behavior even though they protect a wider current operation family.

Their descriptions now state the actual current authority family. This changes discovery/documentation metadata, **not the authorization key or grants**.

## 7. Current gaps

### C1 / D1 — blocker guidance exists, operation resolution does not yet

Stage D now gives clients stable blocker codes, the semantic owner and one or more resolution capabilities. It intentionally stops there.

The future authorized operation catalog must resolve:

```text
blocker resolution capability
        +
current ActorContext
        +
mounted canonical operations
        ->
visible / authorized operation choices
```

This avoids embedding HTTP operation identities in Onboarding and naturally handles one capability authorizing multiple operations.

### C2 — operations-app metadata coverage is incomplete

Catalog Location/schedule operations, Booking assignment operations and Tenancy Organization profile operations have been migrated to `add_capability_route`, but the entire operations app has not yet been audited. Remaining raw `router.add_api_route` surfaces must be classified and migrated when they represent machine-facing capability operations.

### C3 — many administrative responses are untyped

Several current configuration handlers return `object`. That prevents high-quality generated SDK/MCP schemas. Before broad tool projection, important setup operations need explicit response models or a stable schema adapter.

### C4 — public/operator/admin discovery does not yet exist

`CapabilityDefinition.exposure` and operation metadata exist, but there is no runtime authorized operation catalog yet. A public agent therefore must not derive its tool list by blindly converting all mounted OpenAPI operations.

### C5 — readiness is minimum viable setup, not full business configuration

Current readiness answers whether basic appointments/queue/communications prerequisites exist. It does not yet certify every configuration a clinic, barbershop, dental practice or other vertical may need.

Future readiness should be journey-based, for example:

```text
appointment_booking
walk_in_queue
communications
staff_operations
recovery_ready
public_discovery
```

without making Onboarding own the underlying facts.

### C6 — staff-management/permission administration is a current blocker

The inspected Tenancy command/API surface supports Party/contact/identity operations and initial operational-authority bootstrap, but no supported machine-facing lifecycle has yet been found/proven for creating, listing, changing and revoking employee Representation/capability grants.

This means Request Engine must **not** yet claim complete self-service administration for the user's target model of public patient agent + private employee/admin agents.

Do not solve this by adding permissions inside the tool gateway. Tenancy must own the lifecycle because it is authoritative identity/delegation state. A proper design must cover at least:

```text
create or associate employee Principal/Party
create delegated Representation/grant
list effective grants/scopes
change grant set
revoke/suspend delegated authority
audit who granted/revoked what and when
prevent cross-tenant or self-escalation
invalidate/reject stale authority promptly
```

The exact persistence model must be audited before exposing commands.

### C7 — fresh business Party bootstrap is not yet proven

Onboarding can detect the absence of the Organization business Party, but the inspected API surface has not yet established a safe owner-backed operation that creates that Party from a truly fresh tenant state. This gap must be resolved or explicitly delegated to a deployment/provisioning boundary.

## 8. Tool suitability for setup operations

The READY operations above are generally good admin-tool candidates because they are explicit owner commands with authority/idempotency semantics.

Recommended default audience:

```text
tenancy operational-authority bootstrap          admin
Organization profile/contact management          admin
Catalog configuration                            admin
Booking Resource/supply configuration            admin
Queue creation/configuration                     admin
Communications configuration                     admin
Onboarding readiness                             operator, admin
```

This audience metadata is a discovery default, not a permission grant. Real employee access remains capability/Representation based.

Some operational commands may later be exposed to `operator` as policy requires; do not widen them merely because an agent could technically call them.

## 9. Stage C/D implementation completed so far

- operations app maps `CapabilityRequired` to the canonical 403 response rather than allowing a missing capability to become an unhandled server error;
- Catalog Location/profile/schedule operations use `add_capability_route`, explicit stable operation IDs and `catalog.manage` gates;
- Booking Resource creation has an explicit stable operation ID;
- Booking assignment/create/retire/availability operations use `add_capability_route`, explicit stable operation IDs and `booking.manage_supply` gates;
- Queue creation has an explicit stable operation ID;
- Tenancy operational-authority bootstrap has an explicit stable operation ID;
- Tenancy Organization profile/contact operations use a distinct `organization.manage_profile` capability and canonical operation IDs;
- existing Communications channel-policy configuration already follows the canonical route/capability pattern;
- capability descriptions for Catalog and Booking were reconciled with current behavior;
- Onboarding readiness blockers are typed as `code + owner + resolution_capabilities` across Party, Location, appointments, Queue and Communications sections;
- architecture/module tests protect capability failure mapping, operation metadata relationships and blocker semantics.

No PostgreSQL schema or owner transaction semantics were changed by this work.

## 10. Stage C exit criteria

Do not claim complete administrative self-service until all are true:

1. every minimum readiness blocker has a supported owner operation or an explicit provisioning owner that can resolve it;
2. staff/authority lifecycle has a supported admin journey, not SQL-only setup;
3. configuration operations carry canonical operation/capability/owner metadata and typed schemas sufficient for safe tool projection;
4. operator/admin capability failures return structured 403s;
5. current grants can represent the intended public vs receptionist/operator vs admin separation without granting broad accidental authority;
6. an end-to-end admin journey can bootstrap a fresh Organization to a chosen readiness state using only supported APIs/provisioning boundaries;
7. a lower-authority Principal is adversarially proven unable to execute the admin operations even when it knows their exact HTTP/tool identities.

Stage D blocker semantics are now in place. Stage E authorized tool-catalog work may begin as infrastructure, but it must not claim safe administrative completeness until the authority/provisioning blockers above are resolved and adversarially proved.
