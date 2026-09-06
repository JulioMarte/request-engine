# Cross-tenant identity and shared capacity — implementation design

Status: Current implemented capability under pre-production cohesion/rebaseline optimization. Acceptance of changes to this capability is gated by exact-head CI/evidence; historical V3 freeze/release terminology is not authority for the current product model.

## Goal

Allow one real-world indivisible capacity—for example a doctor, consultant, stylist or technician—to be represented by tenant-local Resources in multiple Organizations without permitting overlapping commitments and without exposing one tenant's booking metadata to another tenant.

## Non-negotiable boundaries

- `Organization` remains the tenant security and administrative boundary.
- `Party` remains tenant-local; this capability does not create a global customer/patient directory.
- `Resource` remains tenant-local and keeps Organization-specific capacity and qualification configuration.
- Resource-at-Location eligibility is represented by `ResourceLocationAssignment`; recurring contextual availability is represented by `ResourceLocationAvailability`.
- A Resource may have temporally overlapping assignments in different Locations. This is eligibility/provenance, not independent duplicated capacity. Overlap for the same Resource and same Location remains prohibited.
- `CapacityClaim` remains the sole authoritative capacity-consumption ledger, so commitments against one Resource serialize on that Resource regardless of how many Locations make it eligible.
- Cross-tenant identity correlation never grants cross-tenant read authority.
- Shared-capacity conflicts expose only ordinary availability/unavailability semantics.
- Government identifiers, email addresses, phone numbers and provider account IDs are not public or primary identifiers.
- Unbound Resources remain tenant-local and consume no Location eligibility until an assignment exists.
- Initial shared capacity applies only to `exclusive` Resources.

## Implemented model

### GlobalIdentity

`GlobalIdentity` is an opaque control-plane identity for a real-world person or organization. It is not a public capability identifier and does not itself grant access to tenant data.

No automatic identity matching by email, phone, government identifier or provider identifier is performed. `evidence_ref`, when present, is an opaque control-plane reference rather than tenant-readable PII.

For `kind='person'`, PostgreSQL allows at most one active `SharedCapacityIdentity` per `GlobalIdentity`. The trigger locks the GlobalIdentity while checking cardinality, so concurrent root creation cannot split one known person's mutex. Organization identities may represent multiple independent logical capacities and may therefore have multiple active roots.

This cardinality rule cannot detect two different `GlobalIdentity` rows that control-plane operations accidentally created for the same real human. Correct global identity correlation is therefore an explicit control-plane trust responsibility.

### SharedCapacityIdentity

`SharedCapacityIdentity` is the implemented schema name for the hidden serialization root representing one indivisible physical/logical capacity shared by tenant-local Resources.

The conceptual term “shared root” is used throughout transaction documentation, but the persisted/API identifier remains `SharedCapacityIdentity` in this version. Renaming it is nomenclature cleanup, not a correctness requirement, and is deliberately not mixed into correctness hardening.

### SharedCapacityBinding

`SharedCapacityBinding` is explicit trusted authorization from a tenant-local Resource to a `SharedCapacityIdentity`.

The binding records the shared identity, Organization, Resource, status, validity, authorization provenance, creation provenance, revocation provenance and monotonic revision. A binding is never inferred from matching attributes or UUID knowledge.

Activation/revocation serializes on `Resource → SharedCapacityIdentity`. Activation backfills private shared links for already-live local claims while those roots are locked. Revocation blocks new use of the binding while preserving historical claim links. Rebinding a Resource to a different shared root is rejected while live claims still carry provenance for the previous root.

### SharedCapacityClaimLink

`SharedCapacityClaimLink` connects an authoritative `CapacityClaim` to the shared root it consumed. It is private serialization provenance, not a second capacity ledger.

The link deliberately does not duplicate interval, quantity, Reservation, Party, Offering or tenant-visible appointment metadata. `CapacityClaim` remains the authoritative source for those facts. Links survive binding revocation so an existing commitment does not disappear from serialization history.

## Control-plane authority

Global/shared identity and binding mutation is restricted to trusted `request_engine_admin` functions:

- `request_admin.create_global_identity(...)`;
- `request_admin.create_shared_capacity_identity(...)`;
- `request_admin.activate_shared_capacity_binding(...)`;
- `request_admin.revoke_shared_capacity_binding(...)`.

The private shared-capacity tables are SELECT-only even for `request_engine_admin`; direct DML is revoked so audited mutation functions cannot be bypassed. `request_engine_app` and `request_engine_worker` cannot enumerate or mutate this private state.

Every creation, activation and revocation requires a non-empty `authority_ref` and reason and appends an immutable authority event. `authority_ref` is a caller-supplied business/control-plane reference, **not** an authenticated actor identity. Authority events independently stamp database session provenance and trusted request execution context when present.

`GlobalIdentity` and `SharedCapacityIdentity` have schema-level retired states, but this capability does not expose a supported retirement command. Identity merge/split and retirement remain separate lifecycle work; they must not be advertised as implemented operations.

## Runtime role and RLS boundary

The pre-RLS CapacityClaim tenant guard exists because `guard_capacity_claim()` is `SECURITY DEFINER` and must inspect private cross-tenant provenance before ordinary RLS `WITH CHECK` can protect the statement.

The guard applies to the actual `request_engine_app` group role and to inherited app login roles only when the current role is neither superuser nor `BYPASSRLS`. Bootstrap, schema-owner and administrative sessions are therefore not falsely classified as application runtime merely because PostgreSQL reports inherited role membership.

For actual app runtime, foreign and nonexistent CapacityClaim probes are rejected on tenant context before privileged cross-tenant lookup, preventing the security-definer trigger from becoming a foreign-row existence oracle.

RLS/GUC context remains defense-in-depth. This design does **not** claim protection against arbitrary SQL executed with a fully compromised application database credential. Principal/Representation authorization, least-privilege credentials and trusted transaction bootstrap remain part of the security boundary.

## Booking transaction and lock topology

The tenant-local Resource remains the first capacity root. For bound Resources, Booking additionally serializes against hidden shared roots.

Canonical ordering is:

1. lock the existing business root/children required by the command;
2. collect every affected tenant-local Resource;
3. deduplicate and lock local Resources in stable UUID order;
4. resolve active shared bindings through the protected runtime function;
5. deduplicate and lock corresponding `SharedCapacityIdentity` rows in stable UUID order;
6. revalidate final authoritative capacity state;
7. mutate `CapacityClaim` state;
8. emit dependent audit/outbox consequences.

`request_cmd.lock_shared_capacity_roots(organization_id, resource_ids)` validates tenant context and Resource ownership, locks supplied local Resources itself in stable order and only then locks hidden shared roots. Correctness therefore does not rely on an undocumented caller-only ordering precondition.

Reschedule collects the union of old and new Resource ids before releasing old claims or acquiring replacements, preventing inverse old/new-root lock order and preserving self-overlap semantics.

A reschedule Outbox fact also preserves the released Reservation coordinates (`old_location_id`, `old_start_at`, `old_end_at`) before the authoritative row is moved. This is required because shared/local claim history may continue to change after commit and a delayed lifecycle consumer must not infer which historical slot was released by looking at the latest replaced claim or current Reservation location. The historical coordinates drive only released-slot recovery; capacity locking and current Reservation reconciliation continue to use the normal authoritative Booking state.

## CapacityClaim lifecycle and provenance

Shared capacity makes claim history security-relevant. PostgreSQL enforces that:

- new claims start `active` and cannot pre-populate replacement edges;
- released claims cannot reactivate;
- a released Reservation claim may advance to `replaced` only as part of legitimate replacement provenance;
- `replaced` is terminal;
- completed release/replacement provenance cannot be rewritten;
- linked claims cannot rewrite organization, Resource, requirement, Hold, interval, quantity or creation time underneath an append-only shared link;
- Hold claims may acquire a Reservation id once during legitimate promotion, but existing Reservation provenance cannot be retargeted;
- when Hold and Reservation coexist on a promoted claim, subject, OfferingVersion, location and interval must agree;
- replacement targets must be active claims for the same Organization, Reservation and requirement; self-reference and cycles are excluded by the supported transition protocol;
- contextual Reservation replacement records the authoritative `resource_location_assignment_id` on each replacement claim, preserving the Location eligibility/provenance that justified that commitment.

## SlotOffer transaction and integrity model

Queue owns the outer SlotOffer issuance transaction. Each speculative Resource combination uses a nested transaction/savepoint around its complete local/shared lock set, final validation and Hold/Claim writes. A lost combination rolls back its writes **and locks** before Queue tries another eligible combination. PostgreSQL `23P01` therefore never leaves the outer Queue transaction unusable.

### Creation and offered-state integrity

SlotOffer creation locks semantic sources in this order:

1. `SlotOpportunity`;
2. `WaitlistEntry`;
3. `CapacityHold`.

It proves that the Opportunity is open, WaitlistEntry active, Hold live/unexpired, subject identity matches, Offering/OfferingVersion and locations agree, Hold interval equals the Opportunity interval, and the offer does not outlive the Hold or Opportunity start.

The offer's Organization, source ids, expiry and creation timestamp are immutable. A lifecycle status transition must advance revision.

Deferred consistency checks ensure an offer that commits in `offered` state still points to a valid open Opportunity, active WaitlistEntry and live coherent Hold after all writes in the transaction.

### Accepted terminal integrity

A SlotOffer cannot be forged into `accepted` by changing only its status. At commit, an accepted offer requires:

- its `CapacityHold` to be `consumed`;
- its `SlotOpportunity` to be `filled`;
- its `WaitlistEntry` to be `fulfilled`;
- complete Hold-to-Reservation CapacityClaim promotion;
- promoted claims to resolve to one coherent Reservation;
- that Reservation to be confirmed at the acceptance transition.

Later legitimate Reservation cancellation/reschedule is not prohibited; the acceptance check establishes a coherent transition and historical provenance rather than requiring the Reservation to remain forever active.

### Historical source provenance

A Hold, WaitlistEntry or SlotOpportunity may retain its baseline mutation semantics before any SlotOffer references it. Once referenced by a SlotOffer, material fields that define the meaning of that source become immutable underneath the offer. Revision and lifecycle transitions remain governed by their normal contracts **and by the SlotOffer state machine**: while a SlotOffer remains unresolved in `offered` state, its Hold must remain live, its WaitlistEntry active and its SlotOpportunity open.

This boundary prevents a stable SlotOffer id from silently changing historical meaning while avoiding an unnecessary breaking restriction on unrelated pre-offer baseline operations.

## Capacity-conflict error boundary

PostgreSQL `23P01` is normalized to ordinary capacity-unavailable semantics only for operations that may acquire new capacity:

- direct Booking;
- Reservation reschedule;
- SlotOffer Hold acquisition.

Cancellation, SlotOffer acceptance/promotion and release operate on already-owned capacity. Unexpected `23P01` from those paths propagates as an invariant failure rather than being disguised as normal contention.

The public Booking API returns the same opaque `appointment_unavailable` response for local and shared contention. The global HTTP integrity handler does not translate arbitrary `23P01` errors into Booking failures.

### Post-V3 booking API surface note (F7d)

The F7 arrival-estimate slice touched Booking's API composition (`api/__init__.py`, `api/errors.py`) and `reservation_commands.py` read plumbing without touching capacity semantics: it added a public `appointments.record_arrival_estimate` capability whose command takes only the reservation row lock, never resource locks, and records no capacity claims; its typed errors (`ReservationNotConfirmed`, `ArrivalEstimateInvalid`, revision conflict) ride the existing booking error envelope. Shared-capacity lock order, `guard_capacity_claim` and the `23P01` boundary above are unchanged by that slice.

### Post-V3 operator day-board composition note (F7)

The operator day-board slice also touches Booking API composition, but it is read-only. `/v1/appointments/day-board` reads the tenant-scoped `request_read.reservation_day_v1` `security_invoker` projection under `appointments.day_board`; it creates no Reservation or `CapacityClaim`, acquires no capacity root, and cannot alter shared-capacity serialization. Foreign-tenant rows remain hidden by the ordinary tenant transaction/RLS boundary, so shared-capacity privacy and the lock topology above are unchanged.

### Post-V3 http bootstrap composition note (S0b-R2)

The S0b-R2 party-governance slice touched `bootstrap/http.py` composition plumbing only: it passes the deployment-supplied acting-operator capability source through to the entrypoint's operator resolution (the relay admitted by `platform.acting_for_operator` then runs semantic capability checks against the *operator's* tenant-filtered grant set). It introduces no shared-capacity surface, no cross-tenant read or write path, and no change to lock order or the `23P01` boundary above; all party/revision/staff mutations remain strictly tenant-scoped and enforced by the relay's fail-closed checks described in `docs/v3/38` §9.1.

### Current contextual Booking model

F1 operational profile/contextual supply is now the sole Resource-at-Location scheduling model used by current Booking. The pre-launch compatibility structures `resources.location_id` and `availability_schedules` are removed from the effective schema; current code must not recreate or read them.

For contextual direct booking and Reservation reschedule:

- the tenant-local `Resource` remains the local capacity root;
- `ResourceLocationAssignment` is Location eligibility/provenance only and never replaces `CapacityClaim` or `SharedCapacityIdentity` serialization;
- a Resource may be eligible through overlapping assignments in different Locations; this does **not** create independent capacity copies because all commitments still consume the same Resource capacity and, when bound, the same hidden shared root;
- assignments for the same Resource and same Location may not overlap, preventing ambiguous duplicate contextual provenance for that Location;
- recurring Resource-at-Location availability comes only from `ResourceLocationAvailability`; Location timezone/operational constraints come from the assigned Location;
- direct Booking revalidates Offering, Location, assignment, schedule, commercial terms and Resource observations before claim creation;
- Reservation reschedule first authorizes the acting principal against the Reservation's existing `subject_party_id` under `MANAGE_APPOINTMENT_SCOPE`, subject to the explicit operator-override contract;
- Reservation reschedule locks the union of old and replacement Resources before replacing claims, resolves and locks selected assignments, checks Resource availability revisions, Location operational revision, assignment revisions, schedule/exceptions and contextual commercial terms, and rejects stale configuration fingerprints;
- reschedule preserves the Reservation's committed amount/currency/planned-duration semantics; a target whose current contextual terms would alter those committed commercial facts is rejected rather than silently repriced;
- each replacement `CapacityClaim` records the selected `resource_location_assignment_id` so historical commitment provenance does not depend on a mutable or inferred Resource location;
- if a Resource has a shared-capacity binding, direct Booking and reschedule continue through the existing shared-root lock/contended-capacity path;
- local and cross-tenant shared contention remain observationally identical at the public Booking error boundary.

The removal of `resources.location_id` and `availability_schedules` is therefore a pre-launch model consolidation, not a relaxation of shared-capacity serialization. Location assignment answers **where the Resource is eligible**; `CapacityClaim` and, when present, `SharedCapacityIdentity` answer **whether the Resource's capacity is already consumed**. These responsibilities must remain separate.

### F2 geospatial cross-tenant discovery extension

F2 discovery is a publication and read/handoff capability; it is **not** a new shared-capacity authority and it does not use `GlobalIdentity`, `SharedCapacityIdentity`, `SharedCapacityBinding` or `SharedCapacityClaimLink` as discovery identifiers.

For a `discoopt_v1` booking selected from cross-tenant discovery:

- Discovery may expose only tenant-authorized published supply and the approved public Organization/Location/Offering projection;
- concrete Resource selection remains server-side handoff state and hidden provider identity is not serialized into the public token;
- the handoff preserves exact Publication and Offering-to-classification Mapping observations, but neither fact consumes capacity;
- normal tenant `appointments.book` authority is still required after selection;
- Booking resolves the opaque handoff and revalidates Publication/Mapping plus the normal contextual schedule, assignment, terms and Resource observations inside the authoritative booking transaction;
- `CapacityClaim` remains the only capacity-consumption ledger;
- if a selected Resource is bound to shared capacity, Booking follows the same local-Resource → hidden-SharedCapacityIdentity lock topology described above before committing the claim;
- two discoverable tenant-local Resources bound to one real-world shared root therefore still arbitrate on the same hidden mutex;
- a lost local or cross-tenant shared contention race remains the ordinary opaque `appointment_unavailable` outcome and does not reveal the foreign tenant, Reservation, shared-root identity or GlobalIdentity;
- publication or classification revocation can make the discovery handoff stale, but it cannot rewrite or bypass already-authoritative shared-capacity provenance.

The dedicated `request_engine_discovery` runtime role has no authority to enumerate private shared-capacity tables and no generic tenant-table authority. The internal Booking availability gateway is publication-fenced and may calculate slots, but only the normal Booking commitment path can create Reservation/CapacityClaim state. F2 therefore adds a discovery trust boundary without weakening shared-capacity serialization or privacy.

## Privacy contract

A tenant must not learn from a shared conflict:

- the foreign Organization;
- foreign Party/customer/patient;
- foreign Reservation or claim id;
- appointment purpose or Offering;
- private schedule metadata;
- shared-root or identity-linking evidence.

Normal app/worker roles cannot read `global_identities`, `shared_capacity_identities`, `shared_capacity_bindings`, `shared_capacity_claim_links` or `shared_capacity_authority_events`.

A caller legitimately attempting to book a genuinely shared capacity can necessarily learn whether a proposed interval is busy/free. Repeated authorized probes can therefore infer a busy/free pattern. The guarantee is opacity of foreign identity and metadata—not elimination of the availability fact required to make a booking decision.

## Executable evidence

The branch contains PostgreSQL/application tests for:

- app/worker denial of private global-state enumeration and admin SELECT-only private relations;
- runtime-role classification and pre-RLS foreign/nonexistent probe equivalence;
- guessed foreign Resource rejection through protected shared-root locking;
- local-Resource-first and stable shared-root lock ordering;
- simultaneous cross-tenant Booking arbitration and half-open adjacency;
- SlotOffer vs Booking winner orders and speculative fallback without orphan state;
- SlotOffer semantic source locks, offered-state consistency, terminal acceptance consistency and source provenance immutability;
- CapacityClaim non-reactivation, promotion coherence, replacement provenance and linked historical immutability;
- person one-active-root cardinality;
- authority-event database-session/request-context stamping;
- reschedule rollback and simultaneous inverse-root reschedules;
- binding activation/revocation races, backfill, historical-link preservation and unsafe different-root rebind rejection;
- opaque public Booking errors and narrow persistence-level conflict translation;
- contextual direct booking with a globally bound Resource respecting the same hidden shared-capacity mutex;
- contextual Reservation reschedule retaining subject authority, assignment provenance, configuration freshness and the existing local/shared capacity mutex;
- cross-Location assignment overlap remaining legal while same-Location temporal overlap remains rejected;
- absence of the pre-launch `resources.location_id` and `availability_schedules` compatibility schema;
- Resource bootstrap creating a contextual Location assignment even when no weekly availability windows are supplied.

F2 adds required evidence that discovery publication cannot become shared-capacity authority, that `discoopt_v1` does not expose hidden Resource/shared-root identifiers, and that discovery-originated concurrent Booking still resolves through the existing hidden shared mutex with one winner and the normal opaque loser semantics.

Temporal fixtures must use deterministic intervals that remain future-relative for the lifetime of the proof corpus. A calendar date that can silently become historical is not valid evidence for SlotOpportunity/Booking availability semantics; current fixtures therefore use far-future dates where the behavior depends on future eligibility.

Historical V3 release matrices may remain as provenance, but their matrix status is not current product authority and must not be used to reintroduce removed compatibility paths or freeze-era repository shape.

## Residual risks and explicit assumptions

- Two distinct `GlobalIdentity` rows can represent the same real human if the trusted control plane correlates identity incorrectly. The database intentionally does not guess equivalence from PII. Such duplication can fragment the shared mutex and must be prevented/remediated by trusted identity operations.
- A fully compromised app DB credential remains capable of availability denial-of-service through abusive transactions/locks within its database privileges. Operational containment requires least privilege, transaction/statement/lock/idle-in-transaction limits and SQL-injection prevention.
- Legitimate booking probes expose the accepted busy/free fact for the shared physical capacity.
- Request-context GUCs recorded on authority events supplement database session provenance; they are not independently trusted against arbitrary SQL under a compromised session.
- Global/shared identity retirement and merge/split are intentionally unsupported workflows in this capability.
- There is no arbitrary maximum Resource count in `lock_shared_capacity_roots()` because the current product contract permits `0..N` resource requirements. A future cardinality limit must be introduced normatively.
