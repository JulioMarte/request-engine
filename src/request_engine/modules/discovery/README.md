# Discovery module

`discovery` owns the post-V3 F2 capability for explicit cross-tenant published-supply discovery.

## Ownership

Discovery owns:

```text
ServiceClassification mapping semantics
OfferingServiceClassification provenance
DiscoveryPublication lifecycle
published cross-tenant candidate projection
discovery.search_supply
opaque discoopt_v1 handoff issuance state
```

Discovery does **not** own Organization, Location, OfferingVersion, Resource availability, commercial terms, Reservation, CapacityClaim, GlobalIdentity, or SharedCapacityIdentity.

Those remain with Tenancy, Catalog, Booking, or private platform machinery according to `docs/10-module-ownership-map.md` and `docs/v3/24-geospatial-cross-tenant-discovery-contract.md`.

## Trust boundaries

There are two different runtime surfaces.

Tenant configuration runs under the normal operational application role and tenant RLS:

```text
operations.manage_discovery
  -> map/revoke Offering classification
  -> publish/revoke discovery supply
```

Platform search runs under a dedicated discovery database credential that inherits only `request_engine_discovery`. That role is `NOBYPASSRLS` and receives no generic tenant-table privileges. It may execute only the protected candidate/handoff functions required by F2.

The public Discovery process must not receive:

```text
request_engine_app's generic SessionFactory
request_engine_admin credentials
normal Booking appointment-option signing key
generic cross-tenant SELECT authority
```

## Booking composition

Discovery reuses Booking availability only through `booking.contracts.PublishedSlotReader`.

Successful F2 output requires contextual F1 supply with deterministic commercial terms. Legacy tenant-local Booking remains supported, but a slot without F1 commercial/configuration provenance is not emitted by F2.

The client receives an opaque random token:

```text
discoopt_v1.<secret>
```

Resource selection and publication/mapping observations stay server-side. The token does not serialize Resource IDs or shared-capacity identity.

When the user books, normal tenant Booking authority is still required. Booking resolves the handoff under tenant context and PostgreSQL revalidates/fences the exact publication and mapping inside the same Reservation transaction before commitment.

## Search semantics

Successful searches are globally ordered over the complete accepted candidate set by:

```text
earliest appointment start
distance_meters
stable tenant/location/offering/resource/publication tie-breakers
```

The current implementation exhaustively evaluates at most 200 eligible published candidates. If more than 200 match the geo/time/classification filter, it returns an explicit `discovery_search_too_broad` error rather than silently truncating and presenting an incorrect ranking.

A later batch availability implementation may raise that bound without changing the public ordering semantics.

## Dependency rule

`discovery` may import another business module only through its supported `contracts` surface. Booking must not import Discovery adapters/application/domain internals. Cross-module transactional fencing is implemented through narrow PostgreSQL execution context/functions, not Python repository shortcuts.
