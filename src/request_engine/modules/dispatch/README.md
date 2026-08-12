# Dispatch module

> **V3 status: deferred/incubating. Not a baseline dependency.**

The V2 design explored field-service dispatch lifecycle, destination lineage and feasibility/planning coordination. Those capabilities are outside the first capability-first V3 baseline.

Do not add dependencies from `tenancy`, `catalog`, `requests`, `booking`, `queue`, or `communications` to this module during the transition.

`PlanningRevision`, external field-service feasibility and routing/dispatch-specific commitment semantics should not be preserved in the clean V3 schema solely because they existed in V2.

Reactivate this module only when a concrete field-service vertical needs dispatch as an independent language/policy/lifecycle. Route optimization and GPS telemetry remain outside Request Engine core unless a future product decision explicitly changes that boundary.
