# External reference systems and competitive architecture

Status: **current architectural reference, non-normative**  
Reviewed: **2026-09-19**  
Branch context: `cohesion/system-optimization`

## Purpose

Request Engine should not reimplement mature open-source capabilities merely because they are technically possible to build.

This document records systems that overlap materially with Request Engine and should be reviewed before designing or materially changing scheduling, resource/capacity, queue, healthcare, workflow, identity-adjacent, or agent-facing behavior.

These projects are **references, not authorities**. Their domain models must not be copied into Request Engine unless the owning Request Engine contract and guarantees support the same semantics.

The working question is:

> Does an existing system already solve this problem well enough that Request Engine should integrate, adapt a pattern, or deliberately remain different?

## Reference set

| System | Repository | Why it matters to Request Engine | Classification |
| --- | --- | --- | --- |
| LibreBooking | https://github.com/LibreBooking/librebooking | Multi-resource reservations, schedules, quotas, credits, waitlists, approval/check-in concepts, API, RBAC, extensibility | **Primary competitive reference for resource/capacity scheduling** |
| Cal.diy / Cal.com lineage | https://github.com/calcom/cal.diy | Routing-to-booking, availability, temporary slot holding, booking confirmation, calendar integrations, webhooks, mature scheduling UX | **Primary competitive reference for appointment scheduling** |
| Easy!Appointments | https://github.com/alextselegidis/easyappointments | Simpler self-hosted service/provider/customer appointment model, booking rules, REST/OpenAPI surface | **Baseline scheduler reference** |
| Medplum | https://github.com/medplum/medplum | FHIR-native healthcare backend, identity/data/API/bot infrastructure, healthcare scheduling vocabulary | **Primary healthcare platform reference** |
| Marley Health | https://github.com/earthians/marley | Operational healthcare workflows on Frappe/ERPNext: patients, appointments, encounters, service units, billing, inventory and queue-related workflows | **Healthcare operations / vertical reference** |

## 1. LibreBooking — highest-priority comparison

Reviewed upstream branch: `develop`.

LibreBooking is not merely an appointment calendar. Its core abstraction is **reservation of resources under scheduling rules**, which overlaps directly with important Request Engine concepts.

### Capabilities confirmed in the upstream project

The project documents/supports:

- multi-resource booking;
- reservation waitlists;
- role-based access control;
- quotas and reservation credits;
- usage reporting;
- plugins/extensions;
- ICS calendar integration;
- Docker deployment;
- OAuth2 integration with providers such as Authentik and Keycloak;
- API surfaces for accounts, reservations, resources, schedules, users, groups, accessories and custom attributes;
- resource constraints such as minimum duration, maximum notice and minimum increments;
- reservation approval, check-in/check-out and related lifecycle behavior in the codebase;
- quantity-bearing accessories associated with resources.

Important upstream references:

- repository: https://github.com/LibreBooking/librebooking
- API documentation: https://github.com/LibreBooking/librebooking/blob/develop/docs/source/API.rst
- OAuth2 configuration: https://github.com/LibreBooking/librebooking/blob/develop/docs/source/Oauth2-Configuration.rst
- reviewed `develop` head on 2026-09-19: `c5825a910f7b68b75a08a3c768aa2b2a28591711`

### What Request Engine should study

#### A. Multi-resource reservation semantics

LibreBooking proves that real reservation products need to reason about more than one reservable thing.

Examples:

- practitioner + room;
- machine + operator;
- room + accessory;
- vehicle + equipment.

Before Request Engine adds or changes multi-resource commitment behavior, inspect how LibreBooking represents reservation resources, quantity-bearing accessories, schedule constraints and conflict rules.

Do **not** assume its implementation is correct for Request Engine. Use it to identify edge cases we may have missed.

#### B. Waitlist behavior

LibreBooking has a concrete reservation waitlist implementation.

Request Engine already distinguishes Reservation, QueueEntry and broader request/commitment semantics. That distinction should remain deliberate.

When changing queue/waitlist behavior, compare at least:

- how a waiting request becomes eligible;
- whether promotion is automatic or requires confirmation;
- ordering/fairness;
- cancellation behavior;
- race handling when capacity becomes free;
- notification timing;
- expiry and stale waitlist entries.

The purpose is not to copy LibreBooking's waitlist. It is to make sure Request Engine's richer queue model is solving real additional problems.

#### C. Quotas and credits

LibreBooking has first-class quotas and reservation credits.

This is relevant to Request Engine's future policy/capacity layer because limits may depend on:

- user or group;
- resource;
- schedule;
- time window;
- consumption amount;
- reservation frequency.

Before inventing a new generic quota system in Request Engine, inspect LibreBooking's behavior and identify whether the Request Engine need is actually different.

#### D. Custom attributes

LibreBooking exposes custom attributes for reservations, users, resources and resource types.

This is a useful warning: vertical systems inevitably need custom data.

Request Engine should prefer typed capability/domain extension points over turning its core schema into an unbounded entity-attribute-value model. LibreBooking is useful for studying the product need, but not necessarily as a schema pattern to copy.

#### E. Identity integration

LibreBooking supports OAuth2 identity-provider integration.

Request Engine's authority model is intentionally stricter:

```text
authentication
    !=
authorization
    !=
representation
    !=
resource authority
```

LibreBooking is therefore a useful integration reference, but it is **not evidence that Request Engine should collapse provider identity or group membership directly into business authority**.

### Where LibreBooking does not replace Request Engine

LibreBooking begins close to:

```text
user wants to reserve resource(s)
    -> validate schedule/rules
    -> create reservation
```

Request Engine is intended to begin earlier and remain more general:

```text
request / intent
    -> qualification
    -> authority + policy
    -> eligible fulfillment path
    -> resource/capacity selection
    -> offer / commitment
    -> reservation, queue or other fulfillment state
    -> recovery / delivery / audit
```

The differentiator is not "we can also reserve things." The differentiator must remain the broader transactional request-to-commitment model, stronger authority semantics, agent-safe operations and auditable failure/recovery behavior.

If Request Engine's implementation of plain resource reservation becomes more complicated than LibreBooking's without providing one of those additional guarantees, that is a design smell.

## 2. Cal.diy / Cal.com lineage

Repository: https://github.com/calcom/cal.diy

Reviewed `main` head on 2026-09-19: `6bc45298226f96ff79e0c070c8b2ce39727e8477`.

Cal.diy is the fully open-source MIT-licensed community fork of the Cal.com codebase. The upstream README explicitly notes that commercial/enterprise-only capabilities such as Teams, Organizations, Insights, Workflows and SSO/SAML are not part of Cal.diy.

Important reference:

- headless routing-to-booking flow in the repository lineage;
- mature calendar/availability/event-type abstractions;
- booking confirmation and rescheduling;
- external calendar integration;
- API/webhook/integration patterns;
- temporary hold / revalidation concepts in routing-to-booking flows.

### What Request Engine should study

Study Cal before building generic appointment UX or common calendar-integration behavior.

Particularly valuable areas:

- availability calculation;
- race prevention around slot selection;
- temporary holds and confirmation;
- routing answers to eligible bookable targets;
- reschedule/cancel flows;
- calendar-provider synchronization;
- webhook/event delivery;
- timezone handling.

### Deliberate Request Engine difference

Cal's center of gravity is scheduling.

Request Engine's center of gravity should remain:

```text
request
    -> policy
    -> authority
    -> capacity/commitment
    -> fulfillment
```

If a feature is simply "Calendly but inside Request Engine", prefer reuse/integration or a deliberately thin implementation.

## 3. Easy!Appointments

Repository: https://github.com/alextselegidis/easyappointments

Easy!Appointments is a useful baseline because its model is easy to reason about:

```text
customer
    -> service
    -> provider
    -> working plan / booking rules
    -> appointment
```

It is self-hosted, supports Docker development/deployment paths, email notifications, calendar synchronization and exposes an OpenAPI-described API.

### What Request Engine should study

Use it as the "minimum sufficient scheduler" comparison.

Before adding complexity to ordinary provider/service appointments, ask whether the additional complexity buys a Request Engine guarantee such as:

- multi-resource capacity;
- explicit authority/representation;
- offer/commitment semantics;
- durable recovery;
- queue integration;
- idempotent machine/agent operation;
- stronger auditability.

If not, complexity is probably being added in the wrong layer.

## 4. Medplum

Repository: https://github.com/medplum/medplum

Reviewed `main` head on 2026-09-19: `970581acb3f951b64213b526c84fea043f6d9fa8`.

Medplum is an open-source healthcare development platform built around FHIR.

For Request Engine healthcare work, this matters because healthcare already has established vocabulary and relationships for concepts such as:

- Patient;
- Practitioner;
- Organization;
- Location;
- Schedule;
- Slot;
- Appointment;
- Encounter;
- ServiceRequest.

### Rule for Request Engine healthcare work

Before inventing healthcare-specific core nouns or wire formats, compare the requirement with FHIR and Medplum.

Request Engine should **not become an electronic medical record** and should not recreate clinical data infrastructure.

A likely healthy boundary is:

```text
Request Engine
    = operational request / authority / capacity / queue / commitment orchestration

Medplum or another FHIR system
    = clinical/healthcare system of record when that depth is required
```

FHIR compatibility or mapping should be considered at integration boundaries where healthcare interoperability is a real requirement, not forced into every generic Request Engine core table.

## 5. Marley Health

Canonical repository: https://github.com/earthians/marley

Reviewed `develop` head on 2026-09-19: `c5c66770b46a66cbc2bcf5debe64906a53c26057`.

Marley is a healthcare information system built on Frappe and ERPNext.

It covers a much wider operational vertical than Request Engine should attempt to own directly:

- patient management;
- appointments;
- encounters;
- clinical procedures;
- inpatient workflows;
- laboratory workflows;
- service units / departments;
- billing;
- inventory/pharmacy through ERPNext;
- HR/accounting/assets through ERPNext;
- patient portal;
- healthcare request concepts influenced by FHIR.

Its frontend ecosystem also includes explicit waiting/queue-oriented concepts.

### What Request Engine should study

Marley is valuable for **journey discovery**, not as a core architecture template.

Use it to discover real clinic workflows such as:

```text
appointment
    -> arrival
    -> waiting
    -> encounter
    -> procedure / service
    -> billing
    -> follow-up
```

Request Engine can orchestrate parts of that lifecycle without becoming an HIS/ERP.

### Security warning

An upstream public issue filed in 2026 alleges broad missing permission enforcement across many whitelisted API functions. Treat that as an upstream report, not a proven property of every deployment, but it reinforces a key Request Engine rule:

**never copy a framework's endpoint exposure or permission conventions without independently proving authority at the Request Engine operation boundary.**

Reference: https://github.com/earthians/marley/issues/943

## 6. Competitive boundary

A useful simplified comparison is:

| Concern | LibreBooking | Cal.diy | Easy!Appointments | Medplum | Marley | Request Engine target |
| --- | --- | --- | --- | --- | --- | --- |
| Appointment scheduling | strong | strong | strong | healthcare-oriented | strong healthcare | supported through generic operations |
| Resource reservation | strong | partial/scheduling-shaped | provider-shaped | healthcare-shaped | healthcare-shaped | core capacity concern |
| Multi-resource | yes | varies by flow | limited/simple | representable | vertical-specific | must be explicit where required |
| Waitlist / queue | waitlist | scheduling workflows vary | limited | healthcare modeling possible | operational queue concepts | first-class operational distinction |
| Quotas / credits | yes | not core differentiator | not core | not core | ERP/vertical rules | policy-driven when justified |
| Healthcare semantics | generic only | generic | generic | strong FHIR | strong HIS | integration boundary, not EMR ownership |
| Generic request before booking | limited | routing forms | limited | ServiceRequest exists, healthcare-specific | healthcare workflows | **core differentiator** |
| Capability/representation authority | conventional RBAC/auth | product auth/roles | conventional roles | healthcare auth model | Frappe permissions | **core differentiator** |
| Durable transactional recovery | not central | not central | not central | platform-specific | framework-specific | **core differentiator** |
| Agent-safe canonical operations | not primary | API/integration oriented | API | API/bots | REST/framework API | **core differentiator** |

## 7. Architecture rule: build vs reuse

Before implementing a new generic capability, perform this check:

```text
1. Is this already a mature OSS capability?
        |
        +-- no --> build if it belongs to RE
        |
        +-- yes
              |
              v
2. Does its semantic model fit RE?
        |
        +-- yes --> integrate/reuse/adapt
        |
        +-- no --> document the mismatch
                    before building our version
```

Examples of areas where "build our own" requires explicit justification:

- ordinary appointment scheduling;
- generic calendar synchronization;
- generic waitlist UX;
- generic resource reservation UI;
- healthcare record storage;
- identity provider implementation;
- secrets storage;
- generic durable workflow infrastructure.

The existence of an upstream project does not automatically mean Request Engine should depend on it. It means we owe ourselves a **reuse-or-diverge decision** before writing a competing subsystem.

## 8. What Request Engine must continue to own

The strongest remaining reason for Request Engine to exist is the combination of:

- generic Request semantics;
- policy and qualification before fulfillment;
- capability-based authority;
- representation/delegated operational authority;
- resource/capacity reasoning;
- offers and commitments;
- Reservation versus QueueEntry versus ServiceSession distinctions;
- deterministic/idempotent machine-facing operations;
- transactional correctness;
- durable recovery;
- auditability;
- agent-safe canonical API/tool projections;
- multi-tenant enforcement.

Those properties should receive engineering effort before commodity features already solved well elsewhere.

## 9. Agent instructions for future design work

When working on scheduling, capacity, queue or healthcare behavior:

1. Read this document.
2. Identify the closest upstream reference.
3. Inspect the relevant upstream code/docs, not only its README.
4. Write down the semantic difference before adding a new Request Engine abstraction.
5. Do not import upstream terminology merely because it is familiar.
6. Prefer integration when the external system can remain an optional provider behind a Request Engine boundary.
7. Add/modify Request Engine guarantees only for semantics Request Engine actually promises.
8. Never weaken Request Engine authority, tenant isolation, transactionality or auditability to match an easier upstream design.

## 10. Maintenance

This is a living reference document, not a frozen vendor evaluation.

When a material design decision depends on one of these projects:

- record the upstream repository and branch/commit examined;
- update this document if the comparison materially changes;
- place irreversible Request Engine decisions in an ADR;
- keep external projects non-authoritative unless an explicit integration contract says otherwise.
