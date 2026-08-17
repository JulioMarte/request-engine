# Request Engine V3 invariant release matrix

Status: Phase 6 proof inventory.

The normative invariant definitions and ownership are in `docs/v3/02-pre-sql-contract.md`. This matrix intentionally references those IDs instead of redefining their semantics.

`PARTIAL` means relevant implementation or tests exist, but the Phase 6 release proof is not yet complete. `UNPROVEN` means a specific release proof has not yet been identified. `PASS` requires current-branch executable evidence.

| Invariant | Canonical owner class | Baseline evidence family | Baseline | Release proof phase |
|---|---|---|---|---|
| V3-I01 | DB | tenant authority + adversarial app-role DB/HTTP tests | PARTIAL | 6C/6I |
| V3-I02 | APP | adversarial HTTP Request/Booking/Queue/Waitlist authority tests | PARTIAL | 6I/6K |
| V3-I03 | APP | material Request authority/revocation race + authority HTTP tests | PARTIAL | 6I/6K |
| V3-I04 | DB/ops | worker role and migration role definitions | PARTIAL | 6I |
| V3-I05 | DB | adversarial RLS catalog/fail-closed app-role tests | PARTIAL | 6I |
| V3-I06 | BOTH | trusted execution provenance DB test | PARTIAL | 6I/6J |
| V3-I07 | BOTH | candidate catalog/version references | PARTIAL | 6C/6K |
| V3-I08 | DB | relational tenant keys + foreign-reference adversarial tests | PARTIAL | 6C/6I |
| V3-I09 | BOTH | booking availability/resource adapters | PARTIAL | 6D/6E |
| V3-I10 | APP+DB reference | requests core + schema validation tests | PARTIAL | 6D/6K |
| V3-I11 | BOTH | requests core tests | PARTIAL | 6D/6E |
| V3-I12 | BOTH | idempotency error-contract tests | PARTIAL | 6E |
| V3-I13 | APP | adversarial authority/operator-override/security boundaries | PARTIAL | 6I/6J |
| V3-I14 | APP | request cancellation implementation | PARTIAL | 6D/6K |
| V3-I15 | DB | booking commitment/candidate DB tests | PARTIAL | 6D/6L |
| V3-I16 | DB | capacity hardening + commitment tests | PARTIAL | 6D |
| V3-I17 | BOTH | booking commitment concurrency coverage | PARTIAL | 6D |
| V3-I18 | BOTH | booking commitment capacity coverage | PARTIAL | 6D |
| V3-I19 | transaction+BOTH | booking commitment vertical | PARTIAL | 6D |
| V3-I20 | BOTH | hold/booking implementation | PARTIAL | 6D/6L |
| V3-I21 | BOTH | booking commitment vertical | PARTIAL | 6D |
| V3-I22 | BOTH | hold confirmation/commitment tests | PARTIAL | 6D |
| V3-I23 | transaction+DB | reservation command/lifecycle tests | PARTIAL | 6D |
| V3-I24 | BOTH | reschedule booking core coverage | PARTIAL | 6D |
| V3-I25 | transaction | reschedule booking core coverage | PARTIAL | 6D |
| V3-I26 | APP protocol | booking DB adapter lock protocol | PARTIAL | 6D/6L |
| V3-I27 | APP | booking availability/commitment flow | PARTIAL | 6D |
| V3-I28 | BOTH | reservation lifecycle tests | PARTIAL | 6D |
| V3-I29 | domain/DB | reservation lifecycle/attendance tests | PARTIAL | 6K |
| V3-I30 | APP | lifecycle policy tests | PARTIAL | 6K/6L |
| V3-I31 | DB | first vertical queue tests | PARTIAL | 6D |
| V3-I32 | APP under queue lock | first vertical queue tests | PARTIAL | 6D |
| V3-I33 | DB transaction/lock | queue command implementation | PARTIAL | 6D |
| V3-I34 | BOTH | queue command/HTTP tests | PARTIAL | 6D |
| V3-I35 | architecture | queue model/reader implementation | PARTIAL | 6A/6K |
| V3-I36 | model/DB | waitlist/slot recovery tests | PARTIAL | 6D |
| V3-I37 | APP | SlotOpportunity/booking boundary | PARTIAL | 6D |
| V3-I38 | DB | slot-offer recovery candidate/tests | PARTIAL | 6D |
| V3-I39 | BOTH | slot-offer recovery vertical | PARTIAL | 6D |
| V3-I40 | transaction+BOTH | accept slot-offer recovery flow | PARTIAL | 6D |
| V3-I41 | transaction+BOTH | decline/expiry slot-offer flow | PARTIAL | 6D |
| V3-I42 | BOTH | SlotOpportunity serialization implementation | PARTIAL | 6D |
| V3-I43 | APP under opportunity lock | waitlist/slot selection implementation | PARTIAL | 6D/6G |
| V3-I44 | architecture/APP | durable communications ADR + vertical tests | PARTIAL | 6J |
| V3-I45 | BOTH | communication intent/dedupe implementation | PARTIAL | 6J |
| V3-I46 | BOTH/EXT | delivery store + communication delivery tests | PARTIAL | 6J |
| V3-I47 | APP | provider event/business routing boundary | PARTIAL | 6J |
| V3-I48 | BOTH | ReminderPlan contract + schedule tests | PARTIAL | 6K/6L |
| V3-I49 | BOTH | reminder occurrence/materialization tests | PARTIAL | 6J/6K |
| V3-I50 | BOTH | reminder cancellation/lifecycle tests | PARTIAL | 6J/6K |
| V3-I51 | product boundary/APP | V3 reminder product boundary | PARTIAL | 6K |
| V3-I52 | DB | worker runtime/lease tests | PARTIAL | 6F |
| V3-I53 | DB | expired-lease + communication fencing tests | PARTIAL | 6F |
| V3-I54 | BOTH | worker runtime/dead-letter implementation | PARTIAL | 6F |
| V3-I55 | architecture/APP | worker hardening contract/runtime | PARTIAL | 6F/6J |
| V3-I56 | BOTH | ProviderEvent dedupe implementation | PARTIAL | 6J |
| V3-I57 | EXT/APP | delivery worker/reconciliation contract | PARTIAL | 6F/6J |
| V3-I58 | transaction/APP | outbox pipeline and communication vertical | PARTIAL | 6J |
| V3-I59 | DB | trusted execution provenance DB test | PARTIAL | 6I/6J |
| V3-I60 | BOTH | idempotency contract tests | PARTIAL | 6E |
| V3-I61 | BOTH | idempotency PostgreSQL implementation/contracts | PARTIAL | 6E/6I |
| V3-I62 | BOTH/ops | request_admin authority events + UUID/no-enumeration adversarial tests | PARTIAL | 6I |
| V3-I63 | BOTH | cross-tenant CapacityClaim/Booking/Hold/SlotOffer integration + DB race tests | PARTIAL | 6D/6I |
| V3-I64 | DB+APP | private-table runtime privilege contract + opaque Booking error tests | PARTIAL | 6I/6K |
| V3-I65 | BOTH | binding activation/revocation/rebinding PostgreSQL race tests | PARTIAL | 6D/6I |
| V3-I66 | APP protocol + DB primitive | multi-root lock topology + simultaneous reschedule concurrency tests | PARTIAL | 6D/6L |

## Cross-tenant shared-capacity extension evidence

The extension rows V3-I62..V3-I66 are deliberately `PARTIAL` until a full final-head Phase 6 candidate run consumes this updated inventory. Current executable evidence includes least-privilege denial of global-state enumeration, opaque cross-tenant conflict errors, simultaneous cross-tenant claim arbitration, Hold/Booking contention, SlotOffer/Booking in both winner orders, transactional reschedule rollback, binding activation/revocation races, unsafe rebind rejection, inverse multi-root locking, and simultaneous real reschedules synchronized immediately before the protected shared-root lock call.

The extension preserves the original V3 ownership model: `Resource` remains tenant-local and `CapacityClaim` remains the only consumption ledger. `SharedCapacityIdentity` is an optional hidden serialization root for explicitly bound exclusive Resources, not a global Resource or second commitment ledger.

## Current Phase 6I evidence

CI `#462` on commit `63d2d5004cd74800cb41d08f293e6aa5523f0a70` materially strengthens V3-I01, V3-I02, V3-I03, V3-I05, V3-I08, and V3-I13. The added evidence directly exercises PostgreSQL RLS as `request_engine_app`, verifies fail-closed behavior without tenant context, compares foreign identifiers with nonexistent controls, attacks public Booking/Request/Queue/Waitlist surfaces, keeps operator subject override tenant-bound, and deterministically overlaps a material Request command with Representation revocation.

Those rows remain `PARTIAL`. The current HTTP integration harness does not yet connect through a production login restricted to `request_engine_app`, and the same deterministic material-command race proof is not yet complete for every subject-scoped mutation family. Keeping these rows `PARTIAL` prevents the release registry from claiming more isolation or authority coverage than the executable evidence provides.

## Release-proof rule

Each row must eventually point to at least one executable proof that exercises the owner boundary named by the canonical contract. An application-only test is insufficient for a DB-owned invariant. A mocked concurrency test is insufficient for a lock, RLS, range-overlap, lease or fencing invariant.

The matrix may become more specific as Phase 6 adds proof files. It must not silently change the meaning or ownership of a `V3-Ixx`; such a change belongs in the canonical V3 contract first.
