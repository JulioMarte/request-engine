# Operational Profile & Contextual Supply — Implementation Handoff

Status: current execution handoff for `feature/operational-profile-contextual-supply`.

This document is **informative implementation/status guidance**, not a normative contract.

Normative F1 precedence is now:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
  >
docs/v3/13-operational-profile-contextual-supply-plan.md
  >
docs/v3/14-operational-intelligence-roadmap.md for future features
```

`16-operational-profile-contextual-supply-clarifications.md` is historical adversarial-review provenance; its closed F1 findings have been consolidated into 15/13.

Detailed proof/reconciliation record:

```text
docs/v3/21-operational-profile-contextual-supply-documentation-audit.md
```

---

## 1. Exact proven implementation checkpoint

The canonical Phase H code/proof checkpoint is:

```text
c1966f04c0b36fbe8b5bc41f85bb69e8a6831503
workflow run: 32516044052
```

Every required job on that SHA passed:

```text
Python quality and architecture                         PASS
PostgreSQL 18 F1 operational profile/contextual supply PASS
PostgreSQL 18 V2 design history                        PASS
PostgreSQL 18 V3 repeated bootstrap proof              PASS
Observability runtime contract                         PASS
PostgreSQL 18 frozen V3 compatibility                  PASS
PostgreSQL 18 V3 candidate and verticals aggregate     PASS
```

The F1 job asserts the Alembic head is exactly:

```text
0002_f1_supply
```

Documentation-consolidation commits follow that green code checkpoint. Therefore a **new exact-head canonical run is required after P6 cleanup** before merge readiness, even though Phase H itself is proven.

Feature base / merge base with `development` remains:

```text
9665873a90ecbaa52a17b4aff1ec4d1cd4c70573
```

The branch was still `behind_by = 0` when P5 consolidation began.

---

## 2. Current phase status

| Phase | Status | Disposition |
| --- | --- | --- |
| A — documentation/architecture | COMPLETE; P5 consolidation nearly closed | Contract/plan/roadmap/ADR exist; temporary F1 clarification precedence removed. |
| B — old→new inventory | COMPLETE | `17` remains historical Phase B evidence. |
| C — relational schema | COMPLETE + PROVEN | One unshipped `0002_f1_supply`; schema/RLS/ACL/shared-capacity compatibility proven. |
| D — domain/application model | COMPLETE for F1 | Contextual terms, assignment/schedules, options, commands/errors and booking contracts implemented. |
| E — semantic configuration commands | COMPLETE for F1 | `CreateLocation` and Organization public contacts are implemented/proven; no remaining semantic-surface blocker. |
| F — deterministic query resolution | COMPLETE + PROVEN | Business info, catalog Location/effective supply and contextual slot resolution work. |
| G — direct contextual booking | COMPLETE + PROVEN | `find_slots -> aptopt_v2 -> decode -> book`, stale revalidation, claim provenance and immutable commercial commitment. |
| G — contextual hold/reschedule | ACCEPTED F1 FAIL-CLOSED SCOPE | Full contextual replacement flows are out of F1; `aptopt_v1` legacy behavior remains valid. |
| H — adversarial proof | COMPLETE | Closed at `c1966f04...`, run `32516044052`. |
| P5 — normative docs consolidation | IN PROGRESS / nearly complete | 15/13 consolidated, 16 demoted to history, README precedence simplified, 18/21 reconciled; this handoff is the final status refresh. |
| P6 — repository cleanup | NEXT | Remove feature-only CI trigger, stale tooling/config references, verify no accidental temporary artifacts. |
| P7 — exact-head merge readiness | AFTER P6 | Compare development, inspect full CI, final diff and ADR status. |

The feature is **not yet merge-ready** solely because P6/P7 remain.

---

## 3. Production migration shape

Current post-V3 production-history delta:

```text
migrations/versions/0002_operational_profile_contextual_supply.py
revision = "0002_f1_supply"
down_revision = "0001_initial"
```

The consolidated unshipped revision contains:

```text
operational-profile/contextual-supply schema
commercial source provenance
contextual CapacityClaim assignment provenance
shared-capacity guard compatibility
runtime ACL/RLS hardening
```

Released/frozen history remains immutable:

```text
migrations/versions/0001_initial.py
migrations/sql/v3_candidate/*
migrations/sql/v3_initial/*
migrations/sql/design_chain/*
```

No backfill invents historical contextual assignments or commercial commitments for legacy V3 rows.

---

## 4. Final as-built relational model

Existing relations extended:

```text
organizations
  legal_name
  default_timezone
  default_locale
  default_currency
  operational_status

locations
  structured address
  country_code
  latitude/longitude
  geocoding provenance
  operational_revision

capacity_claims
  nullable resource_location_assignment_id provenance
```

New F1 relations:

```text
organization_public_contact_endpoints
location_public_contact_endpoints
location_operational_hours
location_hours_exceptions
resource_location_assignments
resource_location_availability
resource_location_schedule_exceptions
offering_version_booking_terms
booking_context_terms
reservation_commercial_commitments
reservation_commercial_commitment_context_terms
```

Important physical facts:

```text
contact visibility column = is_public
commercial commitment has NO direct booking_context_terms_id
contextual provenance = 0..N append-only bridge rows
F1 owns guard_f1_exact_revision_step instead of widening frozen V3 guard inventory
request_engine_worker has no final direct privilege on authoritative F1 domain relations
```

See document 18 for the reconciled schema summary; executable `0002_f1_supply` wins on physical SQL details.

---

## 5. Operational truth and schedule composition

Accepted contextual composition:

```text
Location recurring operational hours
APPLY Location-hours exceptions
=
effective Location availability

INTERSECT Resource-at-Location recurrence
APPLY Resource-wide + assignment-specific exceptions
INTERSECT explicit contextual temporal restrictions
THEN capacity
```

Rules to preserve:

```text
Resource additional availability cannot open a closed Location
assignment-specific mutation never silently broadens
Resource-wide mutation is explicit/auditable
recurring wall-clock rules use Location IANA timezone
concrete instants are timezone-aware half-open intervals
DST gap/fold behavior is explicit
```

---

## 6. ResourceLocationAssignment semantics

`ResourceLocationAssignment` proves that a Resource may operate at a Location during an effective range. It does **not** consume capacity.

Key invariants:

```text
same Organization as Resource/Location
one exact Resource+Location scope cannot have ambiguous overlapping ranges
retired assignment cannot be reactivated
identity cannot be retargeted
range edits cannot invalidate existing CapacityClaim provenance
assignment lifecycle advances Resource availability observation
```

Legacy fallback is only for Resources that never entered contextual assignment history. Retiring contextual assignments does not restore legacy wildcard Location eligibility.

---

## 7. Commercial resolution and provenance

Resolution order:

```text
exact ResourceLocationAssignment + OfferingVersion contextual term
>
OfferingVersion base/default term
>
missing required amount/currency/duration => not quoteable/bookable
```

F1 supports context-only commercial resolution:

```text
no base price row
+
context supplies amount/currency
+
OfferingVersion supplies duration
```

Successful contextual booking persists:

```text
Reservation
CapacityClaim with exact assignment provenance
reservation_commercial_commitments material fact
0..N reservation_commercial_commitment_context_terms source rows
audit + outbox + idempotency result
```

No arbitrary “primary” contextual source is chosen for multi-resource bookings.

---

## 8. Appointment option versions

Released legacy path:

```text
aptopt_v1
```

Contextual path:

```text
aptopt_v2
```

`aptopt_v2` binds materially relevant observations including:

```text
Organization/OfferingVersion
start/end
Location
Resource choices
ResourceLocationAssignment IDs/revisions
Resource availability revisions
planned duration
amount/currency
Location operational revision
configuration fingerprint
issued/expires
```

Mixed contextual/legacy Resource choices are represented explicitly; the codec never fabricates assignment IDs for legacy Resources.

---

## 9. Offering lifecycle correction

`OfferingVersion` is append-only/versioned. Do **not** create a test or implementation that mutates it merely to simulate deactivation.

Correct mutable kill-switch:

```text
Offering.active
```

`find_slots` does not advertise an inactive parent Offering. Contextual booking locks/revalidates parent Offering + selected OfferingVersion, so deactivation and booking serialize deterministically.

---

## 10. Contextual hold/reschedule disposition

This is closed F1 scope, not a TODO:

```text
contextual find_slots -> aptopt_v2 -> book    supported
contextual CapacityHold                       fail closed
contextual Reservation reschedule             fail closed
released aptopt_v1 hold/reschedule             preserved
```

The fail-closed boundary exists before released-V3 commitment adapters can discard assignment/schedule/commercial provenance.

The HTTP/router error is machine-readable:

```text
contextual_commitment_unsupported
```

A future contextual hold/reschedule feature must reuse the contextual stale/config/capacity protocol; never pass `aptopt_v2` straight through V3 semantics.

---

## 11. Semantic command surfaces

Implemented/proven responsibilities:

```text
UpdateOrganizationOperationalProfile
SetOrganizationPublicContacts
CreateLocation
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

These are authority/idempotency/audit surfaces; direct generic CRUD is not the business contract.

`ConfigureBookingContextTerms` already supports future-effective ranges, so a separate scheduling command name is unnecessary.

---

## 12. Phase H proof registry summary

Proven in canonical CI:

```text
price mutation vs book
assignment retirement vs book
Location-hours exception vs book
recurring Location-hours mutation vs book
assignment-specific exception vs book
Resource-wide exception vs book
parent Offering deactivation vs book
fresh discovery after Offering deactivation
concurrent context-term overlap writes
concurrent assignment overlap writes
concurrent schedule replacement / stale revision
CapacityClaim assignment provenance immutability
future contextual terms and exact source provenance
context-only commercial booking
multi-source contextual provenance
contextual shared-capacity contention
duplicate human-readable names do not grant authority
DST spring gap / fall fold rejection
foreign/random authority IDs observationally equivalent
foreign/random Location IDs equally absent from discovery
CreateLocation authority/idempotency/tenant safety
Organization public-contact authority/idempotency/tenant safety
business.get_info safe public operational truth
catalog Location/effective-supply filtering
13:00-17:00 any-eligible contextual slot flow
find_slots -> aptopt_v2 -> decode -> book
machine-readable stale aptopt_v2 -> refresh_and_retry
contextual aptopt_v2 reschedule fail-closed before legacy handler
legacy aptopt_v1 reschedule still reaches released handler
released V3 booking regression
frozen V3 compatibility
```

Detailed matrix is in document 21.

---

## 13. P5 documentation status

Closed F1 adversarial clarifications have been consolidated into 15/13.

```text
15 normative contract                     reconciled
13 implementation/closure plan            reconciled
16 temporary clarification amendment      demoted to historical provenance
docs/README precedence                    simplified
18 relational schema                      reconciled to final 0002
21 proof/audit matrix                      updated to Phase H closure
20 implementation handoff                 this document
```

Future F2/F3 questions from the old amendment remain historical inputs for those future feature contracts; they do not reopen F1.

---

## 14. Next step — P6 repository cleanup

Do this before final merge-readiness CI:

```text
1. remove feature/operational-profile-contextual-supply from the push trigger in .github/workflows/ci.yml;
2. remove the stale Ruff ignore for migrations/versions/0003_f1_commercial_context_sources.py;
3. search for obsolete provisional 0003/0004/0005 F1 migration references outside intentional history documents;
4. inspect duplicate commitment-boundary tests and temporary scaffolding, deleting only truly redundant/temporary code;
5. verify frozen V3/release files were not semantically modified by F1;
6. compare against current development and reconcile if development moved;
7. then run P7 exact-head canonical proof.
```

Do **not** remove adversarial tests merely to reduce file count. They are executable invariants.

---

## 15. P7 exact-head merge-readiness gate

On the final cleaned head require:

```text
compare with development
behind_by = 0 or explicit reconciliation
Alembic head = 0002_f1_supply
Python quality/architecture PASS
F1 PostgreSQL PASS
V2 history PASS
V3 repeated bootstrap PASS
Observability PASS
frozen V3 compatibility PASS
aggregate PASS
released V3 booking regressions PASS
no feature-only CI push trigger
no stale provisional F1 migration tooling reference
final docs match code
```

Inspect every prerequisite job, not only the aggregate status.

Only after this exact-head proof should ADR 0012 be considered for `Accepted` and the branch be called merge-ready.