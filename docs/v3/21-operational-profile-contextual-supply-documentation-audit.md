# Operational Profile & Contextual Supply — Documentation Audit and Reconciliation Matrix

Status: current documentation audit for `feature/operational-profile-contextual-supply`.

This document records the reconciliation performed after the implementation reached the consolidated F1 migration and the first substantial adversarial test suite. It is **informative**, not a new normative contract.

Normative precedence remains:

```text
docs/v3/16-operational-profile-contextual-supply-clarifications.md
  >
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Current execution/status handoff:

```text
docs/v3/20-operational-profile-contextual-supply-implementation-handoff.md
```

The purpose of this audit is to answer four questions explicitly:

1. What does the current code actually implement?
2. What has current CI/test evidence actually proven?
3. Where do older design documents no longer exactly describe the as-built implementation?
4. What must still be implemented, tested, reconciled or consciously removed from F1 before merge readiness?

---

## 1. Repository state inspected

Feature branch:

```text
feature/operational-profile-contextual-supply
```

Feature base / merge base with `development`:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

At this audit the branch is:

```text
ahead of development: 206 commits
behind development: 0 commits
```

The last implementation checkpoint before documentation-only commits is:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
```

A compare from that checkpoint to the branch head showed only documentation changes (`docs/README.md` and the implementation handoff), so the implementation tree audited here is the `9d070685...` code state.

The released V3 baseline remains untouched as product/schema provenance:

```text
migrations/versions/0001_initial.py
migrations/sql/v3_candidate/*
migrations/sql/v3_initial/*
migrations/sql/design_chain/*
```

---

## 2. What changed after the earlier handoff

The implementation no longer has a provisional F1 Alembic chain `0002 -> 0003 -> 0004 -> 0005`.

Because Request Engine still has no production/customer-owned data, the provisional unshipped F1 revisions were consolidated into one intended launch revision:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

The consolidated migration now contains:

```text
operational profile/contextual supply schema
commercial source provenance
shared-capacity guard compatibility
runtime ACL/RLS hardening
```

New adversarial proof also exists for:

```text
context-price mutation vs book
Location closure vs book
assignment retirement vs book
future contextual terms
future booking commercial-source provenance
historical CapacityClaim assignment provenance protection
contextual shared-capacity contention
contextual hold/reschedule fail-closed boundaries
```

Therefore any document that still says migration consolidation, future-term proof or assignment-provenance proof are merely planned is stale.

---

## 3. CI evidence at the current implementation checkpoint

The latest implementation checkpoint inspected is:

```text
9d07068520da48950189ff78b70e80fb1bc1786d
workflow run: 32498624044
```

That run produced the following evidence:

| Job | Result |
| --- | --- |
| Python quality and architecture | PASS |
| PostgreSQL 18 F1 operational profile and contextual supply | PASS |
| PostgreSQL 18 V2 design history | PASS |
| PostgreSQL 18 V3 repeated bootstrap proof | PASS |
| Observability runtime contract | PASS |
| PostgreSQL 18 frozen V3 compatibility | CANCELLED by a later branch push while running |
| Required aggregate | FAIL only because the frozen-V3 prerequisite was cancelled |

Important interpretation:

- the current consolidated F1 migration and the current F1 tests **did pass** their dedicated PostgreSQL job on `9d070685...`;
- Python/architecture also passed on that same implementation checkpoint;
- the aggregate is not green because a subsequent documentation push cancelled the long frozen-V3 compatibility job;
- therefore this is stronger evidence than the older pre-consolidation green run, but it is still **not an exact-head all-gates-green proof**;
- after documentation reconciliation is complete, one fresh exact-head canonical CI run is still required before merge readiness.

The older fully green run `32484833747` at `57fc5d7b...` remains useful historical evidence but predates later race/provenance hardening and migration consolidation.

---

## 4. Cross-document reconciliation findings

### 4.1 `13-operational-profile-contextual-supply-plan.md`

Disposition: **keep as the original implementation plan**, but do not read candidate command names as the current implementation inventory.

The plan correctly requires responsibilities equivalent to:

```text
UpdateOrganizationOperationalProfile
CreateLocation
UpdateLocationOperationalInfo
SetLocationOperationalHours
Location public contact mutation
AssignResourceToLocation
RetireResourceLocationAssignment
Resource-at-Location availability
Resource schedule exceptions
Configure/Schedule contextual terms
```

Current implementation names differ intentionally:

```text
UpdateOrganizationOperationalProfile
UpdateLocationOperationalInfo
SetLocationOperationalHours
SetLocationHoursException
SetLocationPublicContacts
ConfigureOfferingVersionBookingTerms
AssignResourceToLocation
RetireResourceLocationAssignment
SetResourceLocationAvailability
SetResourceLocationScheduleException
ConfigureBookingContextTerms
```

`ConfigureBookingContextTerms` already supports effective dating, so a second `ScheduleFutureBookingContextTerms` command is not required merely to satisfy future terms.

Two planned responsibilities remain unresolved as real semantic-surface gaps:

```text
CreateLocation
Organization public operational contact mutation
```

The Phase H race matrix in the plan remains the primary completion checklist; current disposition is recorded in the implementation handoff.

### 4.2 `15-operational-profile-contextual-supply-contract.md`

Disposition: **still normative**, except where `16` supersedes named points.

The implementation satisfies the central F1 contracts for:

```text
ResourceLocationAssignment
Location + Resource schedule composition
contextual price/duration resolution
aptopt_v2 stale observation
authoritative contextual book
immutable commercial commitment
CapacityClaim assignment provenance
legacy V3 compatibility
shared-capacity compatibility
```

The contract still requires semantic responsibilities equivalent to `CreateLocation` and central Organization public operational contacts. Those responsibilities have not been implemented or explicitly narrowed out, so they remain open F1 obligations.

The contract's historical-provenance wording must be interpreted with the as-built multi-source provenance relation described in section 5 of this audit, not as a single contextual source.

### 4.3 `16-operational-profile-contextual-supply-clarifications.md`

Disposition: **still required and still normative on its named points**.

Its closed decisions are represented in the implementation direction:

```text
Location-level exceptions exist
Resource-wide and assignment-specific exceptions remain distinct
Organization is not synonymous with clinic
Organization and Location public operational contacts are separate concepts
Offering identity is not forced to equal future live-workload classification
```

However, the amendment has not yet been folded into `15`/`13`. Before merge readiness, the closed F1 clarifications should be consolidated into the owning normative documents so future readers do not need a permanent three-layer amendment chain.

### 4.4 `17-operational-profile-contextual-supply-implementation-inventory.md`

Disposition: **historical Phase B inventory remains useful**.

It records the old->new decisions made before SQL authoring. It should not be rewritten as present-tense implementation status. The current as-built state belongs in `18`, `20` and this audit.

### 4.5 `18-operational-profile-contextual-supply-relational-schema.md`

Disposition before this audit: **materially stale in several as-built details**.

Required corrections:

```text
contact endpoint column is is_public, not public
F1 is now one consolidated unshipped 0002_f1_supply migration
Reservation commercial provenance supports multiple contextual source rows
reservation_commercial_commitment_context_terms is part of the as-built schema
worker has no direct privileges on authoritative F1 domain relations in final ACL state
F1 uses its own guard_f1_exact_revision_step rather than widening the frozen V3 revision helper
shared-capacity guard compatibility uses a narrow SECURITY DEFINER capacity guard plus tenant-local invoker contextual-assignment validation
```

The relational document should now be treated as an as-built design/reconciliation document, while the executable migration remains authoritative if a discrepancy is discovered.

### 4.6 `19-greenfield-validation-data-premise.md`

Disposition: **current and important**.

It is the reason provisional F1 migrations could be consolidated safely: there is no production/customer-owned F1 data or deployment history to preserve. This premise expires immediately when real production state exists.

### 4.7 `20-operational-profile-contextual-supply-implementation-handoff.md`

Disposition: **current execution handoff; update whenever implementation/proof status materially moves**.

It should not silently promote the ADR, redefine scope or weaken the normative race matrix. It exists to tell the next implementation session exactly where to restart.

### 4.8 ADR 0012

Disposition: **remain `Proposed`**.

A large part of its acceptance condition is now demonstrated, but the branch still has known semantic/API/proof gaps and does not have a clean exact-head merge-readiness run after final documentation/cleanup. Do not mark it `Accepted` early.

---

## 5. As-built commercial provenance and a newly discovered blocker

The original Phase C design stored a direct optional contextual source on:

```text
reservation_commercial_commitments.booking_context_terms_id
```

The implementation later generalized provenance for multi-resource Offerings by adding:

```text
reservation_commercial_commitment_context_terms
```

The current booking writer correctly collects **all** effective contextual source IDs and inserts one bridge row for each source. It no longer chooses a single arbitrary "primary" contextual term.

That is the correct direction because released V3 supports multiple resource requirements and F1 explicitly rejects hidden pricing precedence among selected Resources.

However, the consolidated migration still contains both:

```text
reservation_commercial_commitments.booking_context_terms_id
reservation_commercial_commitment_context_terms
```

and the commitment table still has this structural check:

```text
offering_version_booking_terms_id IS NOT NULL
OR booking_context_terms_id IS NOT NULL
```

The current writer does **not** populate `booking_context_terms_id`.

This is not merely cosmetic.

`BaseBookingTerms.source_id` is allowed to be `NULL` when no `offering_version_booking_terms` row exists, while an exact contextual term is allowed by the F1 contract to provide the missing amount/currency and the OfferingVersion can still provide duration.

Therefore this valid F1 path exists conceptually and in the resolver:

```text
no OfferingVersion base-price row
+
exact effective BookingContextTerms supplies amount/currency
+
OfferingVersion supplies planned duration
=
complete deterministic bookable terms
```

But on successful booking the writer would currently insert:

```text
offering_version_booking_terms_id = NULL
booking_context_terms_id = NULL
```

and then persist the real contextual source only in the bridge table. The row-level CHECK can reject the commitment before the bridge row is inserted.

### Required fix before merge

Treat this as a **P0 correctness blocker**.

Preferred greenfield cleanup direction:

1. remove the obsolete single-source `booking_context_terms_id` column from the still-unshipped consolidated F1 migration unless a concrete consumer still requires it;
2. remove/redefine the row-level source-presence CHECK so a context-only price can commit;
3. keep `offering_version_booking_terms_id` as optional base-source provenance;
4. keep `reservation_commercial_commitment_context_terms` as the canonical 0..N contextual-source provenance;
5. add an integration test proving a context-only price with no base terms can be discovered and booked, with the exact contextual source preserved;
6. add a multi-resource provenance assertion showing every contributing contextual term is preserved and no arbitrary "primary" context is invented.

If a database-level invariant requiring at least one source is desired, it must account for the bridge rows transactionally/deferred; a simple row CHECK cannot inspect another table.

The immutable material commitment itself remains authoritative historical fact even if source references are optional:

```text
amount
currency
planned_duration_minutes
configuration_fingerprint
committed_at
```

---

## 6. Current implementation completeness

### Complete/substantially complete

```text
Phase A documentation/design foundation
Phase B old->new inventory
consolidated F1 relational schema foundation
Organization operational defaults
Location structured operational profile
Location recurring hours
Location one-off hours exceptions
Location public contacts
ResourceLocationAssignment lifecycle
Resource-at-Location recurrence
assignment-specific schedule exceptions
Resource-wide exception composition using released schedule_exceptions
OfferingVersion base commercial terms
contextual effective commercial terms
future contextual terms
aptopt_v2 contextual option observations
legacy aptopt_v1 compatibility
contextual/mixed find_slots
business.get_info operational read model
catalog Location/effective-supply filtering
authoritative contextual book
stale option revalidation
contextual CapacityClaim assignment provenance
immutable Reservation commercial commitment
multi-source contextual commercial provenance
contextual shared-capacity contention proof
config-vs-book core races
historical assignment provenance protection
legacy hold/reschedule fail-closed boundary for contextual choices
```

### Not complete / not proven enough

```text
context-only commercial commitment bug described above
CreateLocation semantic ownership/path
Organization central public contact mutation command
full Phase H race matrix
API/capability end-to-end proof matrix
final foreign-tenant opacity proof for every new public surface
contextual DST gap/fold proof
duplicate display-name authority proof
explicit Offering current-state mutation vs stale book proof
concurrent overlapping context-term write proof
concurrent overlapping assignment/schedule write proof
explicit broad/narrow schedule-exception vs book race
recurring Location-hours mutation vs book proof if required in addition to exception closure
clarification 16 consolidation into 15/13
final relational-document reconciliation
error taxonomy refinement for unsupported contextual hold/reschedule
possible duplicate commitment-boundary test cleanup
feature-only CI trigger cleanup
exact-head full canonical green run
ADR 0012 acceptance decision only after all gates above
```

---

## 7. Contextual CapacityHold and reschedule disposition

The current implementation intentionally does **not** send contextual `ResourceChoice` through the released V3 CapacityHold/reschedule adapters because those adapters do not preserve contextual assignment provenance/revalidation.

Current safe contract:

```text
contextual hold -> fail closed
contextual reschedule -> fail closed
legacy V3 hold/reschedule -> preserve released behavior
```

The guard is placed at the commitment boundary as well as the HTTP reschedule path so internal callers cannot bypass it.

Before merge, make one explicit product-contract decision:

- either F1's Definition of Done accepts fail-closed contextual hold/reschedule because the feature promise requires `find_slots -> book` but not full contextual commitment replacement flows;
- or full contextual hold/reschedule becomes an explicit F1 requirement and must reuse the same assignment/schedule/commercial/stale protocol rather than weakening into V3 semantics.

Do not accidentally implement the second option through a quick pass-through to `PostgresBookingCommitmentCommands`.

---

## 8. Remaining adversarial matrix

Current disposition after inspecting tests/code:

| Scenario | Disposition |
| --- | --- |
| Price changes after discovery before book | PROVEN by deterministic PostgreSQL race |
| Assignment retires after discovery before book | PROVEN by deterministic PostgreSQL race |
| Location closure after discovery before book | PROVEN for Location-hours exception closure |
| Existing CapacityClaim assignment provenance cannot be rewritten | PROVEN |
| Future contextual terms activate at boundary | PROVEN |
| Future booking preserves exact contextual source | PROVEN |
| Contextual shared-capacity contention | PROVEN |
| Contextual hold/reschedule cannot fall into V3 path | PROVEN fail-closed at boundary |
| Assignment-specific schedule exception vs book | NOT EXPLICITLY PROVEN as a race |
| Resource-wide exception vs book | NOT EXPLICITLY PROVEN as a race |
| Recurring Location-hours mutation vs book | NOT EXPLICITLY PROVEN |
| OfferingVersion current state becomes unavailable after discovery | NOT EXPLICITLY PROVEN |
| Concurrent overlapping contextual-term writes | STRUCTURAL sequential/exclusion proof exists; concurrent proof incomplete |
| Concurrent overlapping assignment/schedule writes | STRUCTURAL proof exists; concurrent proof incomplete |
| Duplicate human-readable names cannot confuse authority | NOT EXPLICITLY PROVEN |
| Contextual DST gap/fold behavior | NOT EXPLICITLY PROVEN at F1 integration level |
| Foreign-tenant guessed IDs opaque across all new APIs | PARTIAL; command/RLS proof exists but public-surface matrix incomplete |
| Organization public contact mutation cross-tenant proof | BLOCKED by missing mutation command |
| Context-only price with no base terms can book | CURRENTLY A KNOWN BLOCKER; add proof after fix |

Do not mark Phase H complete by deleting or weakening these rows. A row may leave F1 only through an explicit normative-scope decision with rationale.

---

## 9. Exact continuation order

The safest continuation order is now:

### P0 — fix commercial commitment source model

Resolve the residual single-context column/CHECK conflict and add context-only + multi-source provenance booking proof.

### P1 — rerun focused F1 proof

Run Python quality plus the F1 PostgreSQL job after the P0 fix. Confirm the consolidated migration still boots to exactly `0002_f1_supply` and the released V3 booking regressions inside the F1 runner remain green.

### P2 — close semantic-surface gaps

Decide/implement:

```text
CreateLocation
Organization public operational contact mutation
contextual hold/reschedule final F1 disposition
```

Every retained write surface uses authority + idempotency + audit + tenant/RLS semantics.

### P3 — finish the highest-value Phase H races

Prioritize:

```text
assignment-specific schedule exception vs book
Resource-wide exception vs book
Offering current-state mutation vs book
concurrent overlapping contextual terms
concurrent assignment/schedule writes
Location recurring-hours mutation vs book
duplicate-name authority
DST gap/fold
```

### P4 — API/capability proof

Prove end-to-end:

```text
business.get_info typed public fields
catalog Location/effective-supply filter
find_slots 13:00-17:00 / any eligible Resource
aptopt_v2 -> contextual book
machine-readable stale result
aptopt_v2 contextual reschedule fail-closed while aptopt_v1 legacy path remains valid
foreign-tenant opacity
Organization/Location public contact tenant safety
```

### P5 — normative-document consolidation

Fold the closed F1 parts of `16` into `15` and `13`, update final phase status, and keep future F2/F3 clarifications in the roadmap/owning documents.

### P6 — repository cleanup

```text
remove feature-only push trigger from ci.yml
remove any temporary tooling/workflows
review narrow Ruff exceptions
resolve duplicated commitment-boundary tests if redundant
verify frozen V3 files unchanged
```

### P7 — exact-head merge readiness

On the cleaned final head:

```text
compare with development
require behind_by = 0 or reconcile development
run full canonical CI
inspect every required job, not only aggregate status
verify Alembic head = 0002_f1_supply
verify V3 frozen/release provenance unchanged
verify F1 + V3 regressions green
verify no temporary branch-only CI scaffolding remains
```

Only then consider ADR 0012 `Accepted` and call the feature merge-ready.

---

## 10. Non-negotiable decisions to preserve

Do not fix remaining work by violating these constraints:

```text
0001_initial remains immutable
frozen V3 candidate/design history remains immutable
Resource remains the capacity serialization root
CapacityClaim remains the capacity ledger
ResourceLocationAssignment is eligibility/configuration, not capacity
Location closure wins over Resource additional availability
Resource-wide and assignment-specific exceptions remain distinct
contextualized Resources do not silently regain legacy wildcard Location semantics
price never changes silently during book
historical committed commercial facts are not reconstructed solely from mutable configuration
contextual CapacityClaims retain assignment provenance
shared-capacity locking remains additive
contextual hold/reschedule never silently degrade to V3
semantic commands remain the configuration path; no generic CRUD shortcut
F2/F3/F4/F5/F6 scope does not leak into F1
```

---

## 11. Documentation completion gate

Before merge readiness, documentation is coherent only when:

- `18` matches the executable consolidated migration;
- `20` matches current implementation and exact CI evidence;
- this audit has no unresolved factual discrepancy against code;
- closed F1 clarifications from `16` are folded into `15`/`13` or an explicit decision records why the amendment remains;
- ADR 0012 status matches proof reality;
- `docs/README.md` continues to route readers to the current F1 handoff and normative precedence.

Documentation must distinguish three states precisely:

```text
implemented
proven by current evidence
planned/required but not yet implemented/proven
```

Conflating those states is itself a release-readiness defect.