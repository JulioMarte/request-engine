# Request Engine — Operational Profile & Contextual Supply Clarifications

Status: **historical adversarial-review record; no longer a higher-precedence F1 amendment**.

This document records the findings of the second adversarial documentation audit performed after the original F1 plan, roadmap, contract and ADR 0012 were written.

The closed F1 corrections discovered here have now been consolidated into:

```text
docs/v3/15-operational-profile-contextual-supply-contract.md
docs/v3/13-operational-profile-contextual-supply-plan.md
```

Therefore this document **does not override** those files for F1 anymore. It remains useful for design provenance: it explains which ambiguities were found and why the final F1 contract has its current shape.

The future F2/F3 questions recorded here remain requirements for their owning future features until they are moved into or superseded by those features' own contracts.

---

## 1. Commercial Offering identity is not live workload classification

The original F1 wording risked treating operational labels such as:

```text
new consultation
follow-up
results review
procedure
```

as universal commercial Offering identities.

The corrected distinction, now incorporated into the F1 contract, is:

```text
Offering / OfferingVersion
  = what the business sells/books as a versioned operational-commercial service

Expected workload classification
  = what staff/system expects the live service to resemble operationally

Actual service classification
  = what the delivered live service was classified as during/after execution
```

These concepts may coincide but are not required to share identity.

### F1 conclusion

If a business genuinely configures materially different price, duration, eligibility or booking semantics, separate Offerings/OfferingVersions may be appropriate.

F1 must not create a new Offering merely because a future queue predictor expects a quick follow-up/results-review workload.

### Future F3/F4 requirement

A later feature may persist narrow expected/actual workload classification without rewriting the booked OfferingVersion, for example:

```text
booked OfferingVersion = Cardiology Consultation
expected workload      = results_review
actual workload        = full_consultation
```

Historical expected classification must not be rewritten just because actual service differed.

---

## 2. Location recurring hours require Location-level exceptions

The audit identified that weekly recurring Location hours alone cannot represent:

```text
holiday closure
early close today
one-off Sunday opening
building/utility closure
one-day extended hours
```

Creating one Resource exception per physician is not a valid substitute for a Location-wide operational fact.

The F1 contract now explicitly includes:

```text
LocationOperationalHours
+
LocationHoursException
```

Effective physical availability is resolved first:

```text
Location recurring operational hours
APPLY
Location closures/additional-hours exceptions
=
effective Location operational availability
```

Only then is Resource-at-Location availability composed.

Safety conclusions now incorporated into F1:

```text
Location exception must be same-tenant as Location
overlapping ambiguous state must be rejected
foreign Location IDs cannot become an existence oracle
stale options revalidate current effective Location availability
Resource additional availability cannot bypass Location closure
```

---

## 3. Resource-wide and Resource-at-Location exceptions are different intents

The audit distinguished:

```text
"I will not work Monday at Clínica Brugal"
```

from:

```text
"I will not work Monday"
```

The final F1 contract therefore keeps separate semantics:

```text
Resource-at-Location exception
  -> one explicit ResourceLocationAssignment/context

Resource-wide exception
  -> all applicable assignments for the Resource in its explicit scope
```

A narrow assignment command must never silently affect another Location. A Resource-wide mutation must be explicit and auditable.

Both scopes participate in stale-option/revalidation behavior and neither rewrites historical Reservation/Claim provenance.

---

## 4. Organization is not synonymous with clinic

The audit corrected an implicit domain assumption.

`Organization` is the tenant/security/administrative boundary. Both are valid:

```text
Organization: Dr. Juan Pérez / independent practice
  Location: private office
  Resource: Dr. Juan Pérez
  Offerings
```

and:

```text
Organization: Clínica Brugal
  Locations
  Resources: multiple physicians
  Offerings
```

F1 therefore does not encode constraints that require every Organization to be a facility company or contain multiple physicians.

Future discovery must be able to treat both tenant shapes as participants when publication policy permits.

---

## 5. Organization-level public operational contacts are separate from Location contacts

The audit identified legitimate central business contact endpoints that are not owned by one Location:

```text
central WhatsApp
central appointment phone
central email
```

The final F1 model distinguishes:

```text
Organization public operational endpoint
Location public operational endpoint
PartyContactPoint identity
```

These may share normalized value infrastructure, but ownership/publication/authority semantics are different.

`business.get_info` may expose both central Organization endpoints and Location-specific endpoints without implying automatic override precedence.

---

## 6. Future F2 requirement: canonical cross-tenant service classification

This remains an **open F2 design requirement**, not an F1 schema requirement.

Cross-tenant discovery cannot depend only on tenant-owned display strings because equivalent supply may be named:

```text
Cardiología
Consulta cardiológica
Cardiólogo
Evaluación cardiovascular
```

F2 must provide a canonical classification/mapping mechanism sufficient for a platform query such as `cardiology` / `cardiólogo` to match compatible tenant-owned Offerings while preserving:

```text
tenant-owned display names
versioned Offering identity
explicit publication control
no semantic authority from fuzzy text alone
```

Candidate approaches to evaluate in F2 include:

```text
platform service/category taxonomy + tenant mapping
stable capability/classification codes
curated mapping with controlled aliases
```

F1 intentionally does not choose that persistence model.

---

## 7. Future F3 requirement: interruption/activity authority

The roadmap includes emergency, medical-representative, break and administrative activities.

The audit clarified that recording an operational interruption is **not secretary-only**.

A future F3 command may authorize a physician to start/end their own interruption and authorized staff to record it under tenant policy.

The eventual fact must retain provenance such as:

```text
actor Principal
recorded_by/provenance
Resource
Location/context
category
started_at/completed_at
```

Authorization must derive from actual authority contracts, not UI role names.

---

## 8. Closure disposition

The following F1 issues discovered by this audit are now closed in the owning F1 contract/plan and implementation:

```text
Location recurring hours have explicit Location-level exceptions
Resource-wide and Resource-at-Location exception intents are distinct
commercial Offering identity is not future live-workload identity
Organization is not synonymous with clinic
Organization-level and Location-level public operational contacts both exist
```

The following remain deliberately future-owned:

```text
exact persisted workload-classification model -> F3
workload/ETA estimator -> F4
cross-tenant canonical service taxonomy -> F2
exact discovery ranking/popularity formula -> future discovery/data work
exact ResourceActivity persistence model -> F3
```

This historical document should not be used to reopen closed F1 decisions or to create a new precedence layer. For current F1 semantics, read `15-operational-profile-contextual-supply-contract.md` directly.