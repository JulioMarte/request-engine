# Administrative standing authority inside owner transactions

The scoped administrative surfaces below revalidate current standing authority
inside their owner transaction. HTTP authorization/discovery remains necessary,
but its previously resolved ActorContext alone does not authorize receipt replay
or a later administrative read after the standing grant has been withdrawn.

## Scope and boundary

- Requests definition create, publish-version and set-active Commands, including
  completed receipt replay; definition list/detail and operator inbox Queries.
- Catalog capability vocabulary and exact offering-version configuration Queries.
- Catalog offering-version booking-policy Command, including completed receipt
  replay (explicit pre-production adoption, 2026-10-06). Other bootstrap and
  operational Catalog Commands revalidate their exact active Representation
  before idempotency receipt lookup (explicit pre-production adoption,
  2026-10-06): location create/update/contact/hours/exception, organization
  holiday declaration, resource-capability create, offering create, and base
  booking-terms configuration.
- Booking supply configuration Queries (resources, assignments, terms,
  availability and exceptions); resource creation, assignment/terms creation
  and supersession, assignment retirement, availability replacement and both
  schedule-exception Commands revalidate the exact active Representation before
  idempotency receipt lookup (explicit pre-production adoption, 2026-10-06).
  The durable HTTP regression proves assignment-create replay denial after
  withdrawal. The operation matrix below identifies the additional owner
  transaction evidence and its execution limits.
- Communications channel configuration Query and configure Command, including
  completed receipt replay (explicit pre-production adoption, 2026-10-06).

Owner, HTTP paths, operationIds, transport schemas, idempotency and revision
policies are unchanged. Internal Catalog/Requests Queries now require the trusted
Principal UUID alongside Organization; routers inject it from ActorContext, not
request fields. No new capability or automatic grant is introduced. No new
database function, role, RLS policy or privilege is required.

The narrow shared technical DB helper lives beside the existing tenant authority
reader. It checks a tenant-local active Principal, then an active tenant-plane
operational grant satisfying the required capability (including only aliases
from the canonical capability registry). Nondelegable grants remain sufficient
for execution. A bound execution actor must match both identifiers. Internal
owner callers without task-local context must supply their trusted Principal
explicitly; this is not an untrusted public selector.

## Serialization and failure

READ/PLAN input; LOCK Principal FOR SHARE; VALIDATE standing grant in a separate
statement; then existing Representation/owner/idempotency/resource phases.
Principal locks persist until transaction completion. Grant INSERT/UPDATE bumps
that Principal's authority revision; DELETE is rejected by the append-preserving
grant guard. Supported authority writers serialize through the same Principal.
A revocation that commits before this root is acquired denies the operation;
an operation holding the root may finish before a competing revocation commits.
This is a defined serialization point, not a promise to cancel already admitted
transactions retroactively.

The separate-statement visibility proof assumes the runtime's PostgreSQL
READ COMMITTED isolation: a statement after a winning Principal updater observes
its committed Representation/grant changes. Repeatable Read or Serializable
configuration is not certified by these proofs and must not be silently treated
as equivalent. Representation validity is checked at one database-clock admission
instant; reaching `valid_until` after that check does not retroactively cancel an
already-admitted transaction. Principal/Party activity and writer serialization
remain protected until transaction completion by the held row locks.

Do not lock grant rows after the Principal: direct grant updates may already
hold the grant row while their revision trigger waits for the Principal. Reading
grants in a second statement avoids that lock inversion and observes committed
changes after any winning Principal updater. Representation checks remain
mandatory. For scoped Requests definition Commands, standing authority is checked
before every receipt lookup; Communications configure now uses the same admission
rule with published `communications.configure`. Its receipt/audit namespace
`communications.set_channel_policy` stays unchanged and is not a grant.
Catalog offering policy checks published `catalog.manage` plus the exact
`operations.manage_terms` Representation before idempotency; its internal
`catalog.set_offering_version_booking_policy` namespace is not the grant.
This does not describe unrelated legacy Commands.

The scoped Booking/Communications Queries and Requests definition adapter use
`require_principal_serialized_operational_authority` on that same Session. It
locks the active Principal, then the active authority Party FOR SHARE, and reads
the exact-scope active Representation in a separate statement without a row lock.
All Representation INSERT/UPDATE/DELETE operations trigger the associated
Principal's revision update. A writer already holding a Representation row must
therefore wait behind an admitted reader's Principal root; that reader must not
wait back on the Representation. The previous combination of P-before-R and the
row-before-P trigger produced a real database deadlock under the restricted app
role. The new connection preserves the DB-clock validity instant, scope, tenant,
Party activity, representation selection order and returned authority identity.

Party has no Principal-revision trigger, so its independent SHARE lock remains
necessary. Inspected Party correction/deactivation/restore and revision-ledger
writers update Party/children and append audit facts without later acquiring a
conflicting Principal lock; Principal FK KEY SHARE does not conflict with SHARE.
The operational-authority bootstrap writer already orders Principal before
Party. Future Party or Representation writers must preserve this compatibility.
The old `lock_current_party_authority` primitive and unrelated callers remain
unchanged. This is a scoped connection replacement, not a global lock redesign.

Standing-grant withdrawal maps to the existing 403 `capability_required`
envelope. Missing, withdrawn or expired Representation and inactive authority
Party raise `OperationalAuthorityRequired`, mapped to the distinct 403
`operational_authority_required` envelope. Rejection must create no business
effect, receipt, audit or outbox fact. Runtime roles
retain their existing tenant RLS and column privileges; a failed locking privilege
check is a deployment defect, not permission to widen runtime ACLs.

## Guarantees and deliberate limits

This strengthens INV-AUTHORITY-001, INV-TENANT-001 and INV-PRIVILEGE-001 while
preserving INV-IDEMPOTENCY-001 and INV-ATOMICITY-001. Durable PostgreSQL evidence
must exercise actual restricted runtime roles, both serialization outcomes and
receipt replay after withdrawal. Fixture grants establish plausible initial
authority; they do not seed the command's result or prove onboarding grant setup.
The independent native first-run HTTP journey remains the setup evidence.

This is **not a universal transaction-time authentication/policy revalidation**.
Token possession, native session/identity posture, binding resolution, tenant
feature policy, delegation and agent tool policy retain their existing ingress
or owning command contracts. Existing unrelated commands are not silently
retrofitted. The listed legacy Catalog and Booking Commands adopt exact-Representation
revalidation before receipt lookup, but remain outside **standing-grant**
revalidation inside the owner transaction. Their published capability is still
required at HTTP ingress; an internal receipt namespace is not that capability.
Do not claim they gained the newer standing-grant check or universal
transaction-time authentication. Broader policy linearization needs explicit owner
contracts and lock-order proof rather than an implicit new global policy engine.

## Executed scoped evidence (2026-10-04)

### Additional owner Command proof (2026-10-06)

Catalog offering policy now has ten PostgreSQL tests, including current grant,
Representation and Party withdrawal before fresh intent/replay, plus four
deterministic grant/Representation races with both transaction orders.
Independent connections observe actual blocking; writer-first leaves no ledger,
receipt, audit or outbox, while command-first leaves exactly one ledger/receipt/
audit and denies subsequent replay. The onboarding/Catalog focal run passed
16 tests in 27.62 seconds on isolated PG18.6 port50801, head0025.

Communications policy has equivalent admission races. An additional first-create
race reproduces two missing-row reads under distinct keys: the unique constraint
chooses one creator, ON CONFLICT DO NOTHING preserves that winner, and a separate
READ COMMITTED reread supplies the typed revision conflict to the loser. There
is no broad IntegrityError catch, silent overwrite or durable loser receipt.
The Communications suite passed 12 tests in 14.77 seconds on isolated PG18.6
port57814, head0025. These are scoped proofs, not completed canonical CI.

Fresh PostgreSQL 18.6 in an independent disposable cluster, loopback port 62248,
database `authority_proof`, migrated from 0001 through
`0022_native_provision_session`. No user/shared database or runtime ACL was changed.

```text
uv run pytest \
  tests/integration/f1_operational_profile/test_supply_configuration_reads.py \
  tests/integration/f1_operational_profile/test_catalog_contextual_discovery.py \
  tests/integration/v3_first_vertical/test_request_definition_administration.py \
  -q --tb=short
17 passed in 53.89s
```

The scoped proofs include the two deterministic Principal-root ordering outcomes,
Booking/Communications withdrawal with active Representations preserved, Catalog
detail/vocabulary withdrawal using the restricted application role, and Requests
receipt replay denied after withdrawal despite an ingress resolver still exposing
its old grant. The command journey independently checks committed definition,
version and receipt counts. Runtime fixtures create inherited application LOGINs
with no superuser or RLS bypass; migration/setup connections are not owner runtime
connections. This is scoped regression evidence, not exact-head CI certification,
complete endpoint coverage or production acceptance.

Additional representation-lock regression on isolated PostgreSQL 18.6, port
55433, `request_engine_admin_verify`, head `0023_native_receipt_columns`:
the same-connection deterministic test with the previous guard produced
`DeadlockDetectedError` (40P01), 1 failed / 9 deselected in 10.87s. It observes the
actual writer waiting on the reader via `pg_blocking_pids`, not a sleep-based
race. Restoring the new connection yielded both Booking/Communications cases
passing (2 passed / 8 deselected in 13.71s); both readers completed while the
restricted-role Representation writer waited, then rejected subsequent reads
after revocation with the standing grant still active. No migration or ACL change
was needed. Additional writer-first and inactive-Party cases are durable proof
alongside the existing standing-grant ordering tests, not evidence of universal
write-endpoint coverage.

Final scoped run on that isolated head23 database:

```text
uv run pytest \
  tests/integration/f1_operational_profile/test_supply_configuration_reads.py \
  tests/integration/v3_first_vertical/test_request_definition_administration.py \
  -q --tb=short
16 passed in 112.21s
```

This includes both Representation writer/root outcomes on both read surfaces,
inactive authority Party with still-active Representation and grant, existing
standing-grant races, read reconstruction and Requests definition receipt-replay
withdrawal. Ruff and targeted Pyright passed for the connection, its three
adapters and this regression file. The canonical full-product lane still needs
its own completed run after this fix.

Additional independent review gaps were closed on a fresh Docker PostgreSQL18.6
cluster at loopback62946, database `authority_proof`, installed 0001→0023 with
READ COMMITTED confirmed. Party deactivation versus Booking read and Requests
definition CREATE versus Representation withdrawal each exercise both actual
restricted-role transaction orders using observed blockers. When the writer wins,
Requests leaves no definition/version/receipt/audit/outbox effect; when the Command
wins, exactly one definition/version/receipt/audit survives and subsequent replay
is denied. The Party writer leaves Representation/grants live, isolating Party
activity enforcement rather than capability withdrawal.

Both complete scoped files passed: 20 passed in 71.72s. After adding bounded
coordination/cleanup waits, the six affected race cases passed on the final test
source: 6 passed / 14 deselected in 35.50s. Ruff and targeted Pyright passed.
This adds scoped concurrency evidence, not complete public endpoint coverage or
certification of the still-running canonical product lane.


## Owner operation matrix (2026-10-08)

This matrix records existing admission semantics; it does not add capabilities,
change migration history or retrofit a global authorization engine. Every row
checks exact tenant/Principal/Party/scope Representation before reading an
idempotency receipt. The legacy guard also requires active Principal and Party.
Its SHARE row locks cover Representation, Principal and Party through commit;
owner serialization roots listed below follow that admission and receipt phase.

| Owner operation | Published ingress capability | Exact Representation scope | Subsequent owner serialization root |
| --- | --- | --- | --- |
| Booking resource create | `booking.manage_supply` | `operations.manage_supply` | Active Location; new Resource identity and uniqueness |
| Booking assignment create | `booking.manage_supply` | `operations.manage_supply` | Location, then Resource; availability revision and effective-range exclusion |
| Booking assignment retire | `booking.manage_supply` | `operations.manage_supply` | Resource, then Assignment; both expected revisions |
| Booking availability replace | `booking.manage_supply` | `operations.manage_supply` | Resource, then Assignment; availability revision |
| Booking assignment exception set | `booking.manage_supply` | `operations.manage_supply` | Resource, then Assignment; availability revision |
| Booking resource-wide exception set | `booking.manage_supply` | `operations.manage_supply` | Resource; availability revision |
| Booking contextual terms create | `catalog.manage` | `operations.manage_terms` | Resource, then Assignment; effective-range exclusion |
| Booking contextual terms supersede | `catalog.manage` | `operations.manage_terms` | Resource, Assignment and current Terms; expected terms revision/cutover |
| Catalog Location create | `catalog.manage` | `operations.manage_profile` | New Location identity and tenant key uniqueness |
| Catalog Location information update | `catalog.manage` | `operations.manage_profile` | Location; expected operational revision |
| Catalog Location contacts replace | `catalog.manage` | `operations.manage_profile` | Location |
| Catalog Location hours replace | `catalog.manage` | `operations.manage_profile` | Location; expected operational revision |
| Catalog Location exception set | `catalog.manage` | `operations.manage_profile` | Location; expected operational revision |
| Catalog organization holidays declare | `catalog.manage` | `operations.manage_profile` | Active Locations in stable UUID order |
| Catalog resource capability create | `catalog.manage` | `operations.manage_profile` | New capability identity and tenant key uniqueness |
| Catalog Offering create | `catalog.manage` | `operations.manage_terms` | New Offering/version identity and tenant key uniqueness |
| Catalog base booking terms configure | `catalog.manage` | `operations.manage_terms` | Offering; one immutable terms fact per OfferingVersion |

There is no standalone assignment-supersede Command in this surface: assignment
creation and retirement are distinct Commands, and terms supersession has its
own explicit Command. Exception `set` supports existing and new identities;
the matrix evidence below exercises creation/replay, rather than claiming every
exception update lifecycle variant is independently covered.

`tests/integration/f1_operational_profile/test_configuration_command_authority_matrix.py`
contains 204 real PostgreSQL cases for these 17 operations. Each operation has
fresh-intent and completed-receipt denial after exact-scope Representation,
Principal or Party withdrawal. Representation withdrawal leaves the other valid
scopes live, so accepting any active Representation would fail the proof.
The matrix also exercises both transaction orders versus exact-scope
Representation withdrawal, Principal deactivation and Party deactivation.
Commands and racing authority writers use independent Sessions of actual
restricted application LOGINs; `pg_blocking_pids` proves the contested order.
The synchronization wrapper pauses **after** the real authority SQL and does
not replace admission, receipt, owner-write, revision, audit or transaction code.

An independent privileged observer compares complete owner rows, including
revisions and effective ranges, plus receipts, audit and outbox. Successful
Command admission must produce exactly one receipt and audit, with no outbox;
ordinary replay must preserve all rows. Withdrawal-first must leave every
snapshot unchanged; Command-first must finish exactly once and deny subsequent
replay after withdrawal commits.

**Executed scoped evidence:** isolated PostgreSQL 18.6, Python 3.13 and
current migrations through `0036_webauthn_deadline`; application LOGINs inherit
`request_engine_app`, with no superuser or RLS bypass. The current matrix source
passed **204 tests in 77.32 seconds**. Its fresh-world wrapper exited 1 afterward
because transient `.rsync-tmp` content prevented removal of a scratch database
directory; the pytest JUnit artifact records zero failures/errors. This cleanup
failure must be distinguished from the completed database proofs and corrected
in the disposable harness; it is not a product runtime or release PASS.

```text
bash ../run-pg18-lab.sh authority-matrix head uv run pytest \
  tests/integration/f1_operational_profile/test_configuration_command_authority_matrix.py \
  -q --tb=short --junitxml=.ci/readiness-20261008/authority-matrix.xml
204 passed in 77.32s
```

The neighboring Catalog offering-policy and Communications configure/creation
race suites passed **22 tests in 8.15 seconds** on their own fresh PG18.6 world.
Ruff and targeted Pyright passed for the new matrix. A disposable pytest plugin
replaced only the resource adapter's authority guard with an unconditional grant;
the fresh/withdrawn-Representation case then failed with
`DID NOT RAISE OperationalAuthorityRequired`. The plugin was outside the repo,
used for that single subprocess, and never changed production source or canonical
CI. This demonstrates the negative proof catches a removed admission guard.

The subsequent canonical local current-product run completed with exit 0 and
1676 passing tests, including this matrix; its dated result and environment limits
are recorded in `../testing/pr137-api-production-readiness-2026-10-06.md`. These
executions are not exact-head GitHub CI or production acceptance. They prove the listed
legacy owner contracts, not standing-grant or native-session linearization for
those Commands. Existing Communications configure and Catalog offering-policy
standing-capability checks retain their separate scope described above.
