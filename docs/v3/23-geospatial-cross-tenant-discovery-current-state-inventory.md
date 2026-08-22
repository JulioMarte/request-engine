# Request Engine — F2 Geospatial Cross-Tenant Discovery Current-State Inventory

Status: Phase A implementation inventory for `feature/geospatial-cross-tenant-discovery`.

This document records the old -> new disposition against the exact post-F1 `development` architecture before F2 SQL or runtime surfaces are introduced. It exists to prevent F2 from duplicating F1 truth, weakening ADR 0011 privacy, or accidentally turning a tenant-local reader into a cross-tenant bypass.

## 1. Baseline inspected

F2 starts from:

```text
development@aa485ed19d81316f879bcc3b1bb39b17bc705436
```

The active branch is:

```text
feature/geospatial-cross-tenant-discovery
```

The production Alembic line currently ends at:

```text
0001_initial.py
0002_operational_profile_contextual_supply.py
0003_f1_runtime_acl_completion.py
```

No F2 migration existed at the start of this inventory.

## 2. Disposition legend

```text
REUSE       current concept remains authoritative unchanged
EXTEND      current concept remains authoritative but gains a narrow F2 surface
NEW         F2 needs a new concept because no current owner exists
SUPERSEDE   existing behavior is replaced for F2 only by a stronger explicit contract
OUT         intentionally outside F2
```

## 3. Current -> F2 disposition

| Current component | Disposition | F2 decision |
|---|---|---|
| `Organization` tenant boundary | REUSE | remains security/administrative ownership boundary; discovery publication never transfers ownership |
| Organization operational/public profile | REUSE | projected only when an eligible publication references supply in that Organization |
| Organization public contacts | REUSE | may be projected when publication policy allows; no duplicated discovery contact store |
| `Location` | REUSE | remains authoritative facility/location identity |
| Location coordinates | REUSE | F1 `latitude`/`longitude` are authoritative fixed-location coordinates for F2 proximity |
| Location address/public data | REUSE | projection source; publication controls whether the location appears |
| Location recurring hours/exceptions | REUSE | discovery availability derives from current effective Location availability |
| `Offering` / `OfferingVersion` | REUSE | tenant-owned commercial/service identity remains unchanged |
| tenant display strings/search text | SUPERSEDE for cross-tenant matching | text may help presentation/search hints but is not authoritative cross-tenant semantic classification |
| `ResourceCapability` | REUSE internally | remains tenant booking requirement vocabulary; not sufficient by itself as platform service taxonomy |
| `OfferingResourceRequirement` | REUSE | still defines resource requirements for Booking/availability |
| `Resource` | REUSE | tenant-local capacity/configuration identity; publication does not globalize it |
| `ResourceLocationAssignment` | REUSE | assignment is operational eligibility/provenance and a valid F2 publication scope input |
| assignment availability/exceptions | REUSE | source of current slot truth |
| Resource-wide exceptions | REUSE | continue affecting slot discovery |
| OfferingVersion base booking terms | REUSE | source for deterministic base commercial terms |
| contextual booking terms | REUSE | exact Resource + Location + OfferingVersion effective override source |
| `CapacityClaim` | REUSE | sole authoritative capacity-consumption ledger |
| appointment option generation (`aptopt_v2`) | EXTEND via composition | tenant Booking remains authoritative slot generator; F2 must not fork the scheduling algorithm |
| appointment booking/revalidation | REUSE | selected discovery option is committed only through normal Booking revalidation |
| shared-capacity identity/bindings | REUSE privately | continue serializing physical capacity; never become discovery identifiers or read authority |
| `GlobalIdentity` | OUT of discovery projection | private control-plane identity only |
| `SharedCapacityIdentity` | OUT of discovery projection | private serialization root only |
| shared-capacity busy/free behavior | REUSE | legitimate published supply can reveal only the busy/free fact needed to offer a slot |
| tenant `ActorContext` | REUSE for tenant operations | remains correct for tenant-owned publication/mapping commands |
| tenant Representation authority | EXTEND | add exact discovery-management scope for tenant publication/mapping mutation |
| public FastAPI app | REUSE unchanged | normal tenant business API remains tenant-bound; do not graft platform cross-tenant search into it |
| operational FastAPI app | EXTEND | tenant operators configure mapping/publication through semantic commands |
| generic `request_engine_admin` | OUT of F2 read path | must not become marketplace/search reader |
| existing RLS policies | REUSE | ordinary tenant tables remain non-enumerable across tenants |
| generic cross-tenant SELECT | REJECTED | no app-side RLS bypass or direct table scan |
| narrow SQL `SECURITY DEFINER` protected read surfaces | EXTEND pattern | F2 may expose only an explicitly published projection through a purpose-built function |
| idempotency ledger | REUSE | publication/mapping commands require normal idempotency semantics |
| audit events | REUSE | all authoritative publication/mapping mutation is audited |
| existing capability registry | EXTEND | add F2 discovery/query and tenant operational management capabilities where appropriate |
| existing test architecture | REUSE/EXTEND | F2 evidence joins current-product proof; no permanent isolated `f2_*` lane after integration |

## 4. New F2-owned concepts

The current architecture has no owner for the following truths, so F2 requires new concepts.

### 4.1 ServiceClassification

Platform-owned canonical operational classification used to correlate equivalent tenant Offerings for discovery.

Example:

```text
key = cardiology
```

It is not an Offering replacement and does not carry tenant price/schedule/capacity truth.

### 4.2 OfferingServiceClassification

Explicit mapping:

```text
Organization + Offering -> ServiceClassification
```

The mapping is authoritative only after an approved semantic mutation. Fuzzy text, embeddings or an LLM may suggest a mapping but may not create authoritative equivalence by themselves.

### 4.3 DiscoveryPublication

Tenant-owned, effective/revocable authorization that says a concrete operational supply scope may participate in platform discovery.

It must not copy mutable operational truth. A publication references existing tenant-owned identities and controls exposure intent.

Initial exact publication scope is closed in the F2 contract rather than inferred from arbitrary JSON.

### 4.4 PlatformDiscoveryActor / authority boundary

Cross-tenant discovery requires an authenticated platform-facing actor model that is distinct from tenant `ActorContext` and from database/admin authority.

The discovery actor can authorize the narrow query capability but cannot select arbitrary tenant tables or mutate tenant state.

### 4.5 DiscoveryOption projection

A non-authoritative read projection composed from:

```text
publication
+ canonical classification mapping
+ current F1 operational truth
+ current Booking slot truth
+ geospatial distance
```

It is advisory until normal Booking revalidation commits capacity.

## 5. Module ownership disposition

F2 should introduce a new post-V3 baseline business module:

```text
src/request_engine/modules/discovery/
```

Ownership:

```text
ServiceClassification
OfferingServiceClassification
DiscoveryPublication
cross-tenant published-supply query/projection contract
```

Non-ownership:

```text
Organization/Representation          -> tenancy
Location/Offering/OfferingVersion    -> catalog
Resource/availability/capacity       -> booking
Global/shared capacity identity      -> trusted control plane / existing private schema
transactional communications         -> communications
```

Reasoning: placing F2 inside `catalog` would make a tenant-local catalog owner responsible for global publication authority; placing it inside `booking` would mix marketplace projection with capacity ownership. A separate capability boundary keeps both existing modules authoritative.

## 6. Cross-module connection surfaces

The discovery module must not import another module's adapters/domain/API internals.

Required contracts/facades:

```text
discovery -> catalog published operational projection contract
discovery -> booking published slot-query contract
discovery -> tenancy authority/public-identity contract where required
```

Where a single SQL query is needed for security/performance, that is a reviewed database projection surface, not permission for Python to import another module's persistence adapters.

The SQL projection may join authoritative tables because PostgreSQL is the shared transactional store, but ownership and mutation remain with the source modules.

## 7. RLS / database disposition

Ordinary tables remain tenant-scoped and protected.

F2 cross-tenant read uses a narrow protected function/view surface that:

1. reads only active/effective `DiscoveryPublication` rows;
2. joins only the fields necessary to form discovery candidates;
3. never returns foreign Party, Reservation, CapacityClaim, GlobalIdentity, SharedCapacityIdentity or authority evidence;
4. is callable only through the intended runtime role/surface;
5. performs no mutation;
6. cannot accept arbitrary relation names, SQL fragments or tenant bypass flags.

This is materially different from granting `BYPASSRLS`, admin role membership or SELECT on private tenant tables.

## 8. Geospatial disposition

F1 already persists validated coordinate pairs:

```text
latitude numeric(9,6)
longitude numeric(9,6)
```

Therefore F2 does not need a second geometry truth.

Initial implementation should use a deterministic great-circle distance expression over the existing coordinates unless measured query requirements prove PostGIS necessary. The implementation must keep the calculation behind one semantic adapter/projection so PostGIS can replace the algorithm later without changing F2 contracts.

## 9. Publication scope decision to carry into contract

The minimal useful initial publication is the exact operational combination:

```text
Organization
+ Offering
+ Location
+ optional Resource
```

Rationale:

- Offering-only publication is too broad because a tenant may expose one clinic but not another;
- Location-only publication cannot express which services are published;
- assignment-only publication couples discovery unnecessarily to a Booking persistence detail;
- an optional Resource permits both provider-visible and provider-hidden discovery policies while Booking still resolves actual capacity.

The persisted publication references `offering_id` + `location_id` and optionally `resource_id`. At query time it resolves the current/latest compatible OfferingVersion and current assignment/context rather than storing duplicated price/duration/schedule snapshots.

## 10. Stale/unpublish disposition

F2 adopts this initial rule:

```text
unpublish stops new discovery immediately
but does not itself cancel/rewrite an already valid Reservation
```

A previously returned discovery option is advisory. Booking must revalidate that its publication is still active/effective before commitment. Therefore unpublishing before booking makes the old discovery option stale/unavailable; unpublishing after successful booking has no retroactive effect on the Reservation.

This gives publication revocation operational meaning without corrupting historical commitments.

## 11. Phase A conclusion

No current F1/shared-capacity component needs replacement.

F2 is a narrow additive architecture:

```text
F1 operational truth
        +
explicit canonical mapping
        +
explicit publication
        +
narrow cross-tenant projection
        +
geospatial calculation
        +
normal Booking revalidation
```

The next safe step is the normative F2 contract followed by append-only `0004_*` schema work, provided the migration head is rechecked immediately before creating the revision.