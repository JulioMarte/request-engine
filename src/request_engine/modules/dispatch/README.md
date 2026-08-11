# Dispatch module

Owns field-service dispatch lifecycle, material destination lineage, and field-service feasibility semantics.

`ChangeDispatchDestination` belongs here. Shared capacity authorities and PlanningRevision mechanics remain owned by booking; dispatch coordinates through booking's public contracts when a feasibility decision affects commitments.

No route optimizer or GPS telemetry platform is introduced into core.
