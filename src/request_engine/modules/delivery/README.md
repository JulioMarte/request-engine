# Delivery module

> **V3 status: deferred/incubating. Not a baseline dependency.**

The V2 architecture grouped admission/queue, `ServiceSession`, `Fulfillment`, and correction semantics here. V3 deliberately narrows the first product baseline:

- ServiceQueue and Waitlist ownership moves to the baseline `queue` module.
- `ServiceSession`, `Fulfillment`, `OutcomeScope` coordination and fulfillment corrections are deferred until a concrete execution/outcome capability proves that this independent domain is required.

Do not add dependencies from `tenancy`, `catalog`, `requests`, `booking`, `queue`, or `communications` to this module during the transition.

The existing module is retained temporarily as design memory, not as permission to preserve V2 tables/abstractions in the clean V3 PostgreSQL baseline.

Reactivation requires a concrete use case, updated module ownership/contracts, executable invariants/races where applicable, and an accepted architecture decision if the boundary is material.
