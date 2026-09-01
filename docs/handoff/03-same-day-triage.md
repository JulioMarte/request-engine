# Handoff 03 — Same-Day Triage (S5 / F7e subset)

Audience: the next engineer/agent with zero context. The normative semantic contract is
`docs/v3/36` §7 — read it; this file only orients you. Implementation plan slot:
`docs/v3/37` S5. Round-3 audit framing: `docs/v3/37` R3-3.

## 1. The problem

`docs/v3/37` R3-3: **urgent selection, squeeze-in and stepped-out have zero truthful
representation; every workaround fabricates durable lies.** Verified in code: the only
selection mechanism is `call_next`
(`src/request_engine/modules/queue/application/commands/call_next.py`) — earliest eligible
waiting entry, strictly FIFO. `QueueEntryStatus`
(`src/request_engine/modules/queue/contracts/service_queue.py`) has no vocabulary for
"called out of order", "temporarily unavailable", or "was called and did not respond but
is still in line". A receptionist who walks an urgent patient to the front today can only
cancel-and-rejoin (destroying arrival order truth), mark a false `no_show` (a durable lie
that also frees capacity), or keep it all in her head — which is exactly what F7 exists
to eliminate (criterion 5, the week-3 test, in `docs/v3/36` §0.1).

## 2. The closed semantic vocabulary (doc 36 §7, quoted verbatim)

```text
operator_select   call a specific waiting entry now; reason recorded from a closed reason set
recall_hold       entry temporarily not-callable until a condition
                  (closed kinds: until_time, until_event, until_customer_initiates);
                  reason is optional annotation, the gate is queue truth
skip              recorded non-terminal defer of the FIFO head; entry returns to waiting
```

Operationally at a clinic:

- `operator_select` — "room this urgent patient now, past the line." Not a reorder; a
  selection fact with an audited reason from a closed set (e.g. urgency, booked
  appointment start, operator override). The bypassed entries stay `waiting`, in order.
- `recall_hold` — "stepped out / went to pay / went for labs; don't call me until…"
  The entry stays in the queue but is temporarily not-callable. The condition kinds are a
  closed set: `until_time`, `until_event`, `until_customer_initiates`. The gate is queue
  truth, not the free-text reason.
- `skip` — "the person at the head of the line isn't there right now; go to the next."
  Non-terminal: the entry returns to `waiting` and remains in the derived order.

Preserved unchanged per §7: FIFO default and tiebreaker over `(admitted_at, id)`; position
is derived, never a stored counter; one active entry per subject per queue; no scoring, no
tenant-configurable policies. Terminal exits (`no_show`, `leave`) remain the only
permanent departures. `docs/v3/36` §9 adds: no auto-dispatch without operator commitment.

## 3. What exists vs. what must be created

Exists (verified): queue module machinery — `call_next` selection, queue entry codec/lock
path (`queue/adapters/db/live_queue_locking.py`, `service_queue_commands.py`), check-in
and no-show persistence (`queue/adapters/db/check_in.py`, `mark_no_show.py`), staff read
surface (`queue/api/live_read_router.py` via `request_read.live_service_staff_v1`),
workload classifications, live queue contract (`queue/contracts/live_queue.py`).
Intake controls (`service_queue_intake_controls`, migration 0011) already model
queue-level gates, but nothing models per-entry holds or out-of-order selection.

Must be created:

- Three named, audited, idempotent operator commands (`operator_select`, `recall_hold`,
  `skip`), each with its closed reason/kind sets, registered as queue-owned capabilities.
- Selection semantics over the **derived** order: reordering is expressed as ordered
  facts, never a mutable position. The degenerate case (no holds, no priority facts, no
  override) must select **byte-identically to today's `call_next`** — this equivalence is
  a required acceptance proof (doc 36 §10).
- Live-capacity honesty: a held entry is not projected as imminent; where truth runs out
  the projection degrades to `partial`/`indeterminate`, never guesses (§7; live_capacity
  consumes this only through supported queue contracts — `queue/contracts/live_capacity.py`
  is the existing cross-module surface).
- Read surfaces that expose holds: the staff read (`queue.staff_read`) and the day board
  must show held/skipped state truthfully, including why an entry is not-callable.
- Race surface: everything above mutates the same queue state that `call_next` locks.
  Doc 37 S5 is explicit: `call_next` is the most invariant-sensitive transaction in the
  repo; this slice needs its own PostgreSQL proof lane and must not be bundled with other
  slices.

## 4. Dependencies and authority

- **Day board (handoff 02) lands first.** Triage without a truthful board just moves the
  lies; the board is also how the operator sees who is `waiting`/`held`/`skipped`.
- All three commands are operator-authority mutations: `source_kind=operator`. If a bot
  relays them (Chatwoot-style), the acting-operator relay applies — verified implemented
  in `src/request_engine/platform/security/acting_operator.py` (`platform.acting_for_operator`
  admission permission; RE verifies in-transaction that the referenced operator exists,
  is active, same organization, holds the capability; `ActorContext.acting_operator_principal_id`
  in `platform/security/context.py`). See `docs/v3/38` §9.1 for the rule.
- Idempotency keys scoped to the effective principal; audit keeps both identities.

## 5. Proof expectations and open owner decisions

Proofs (per doc 36 §10 F7e row):

- Degenerate selection equivalence: no facts -> identical `call_next` result.
- Held entries excluded from automatic selection AND from imminent projection.
- Every out-of-order move audited.
- **PostgreSQL race proofs on the selection lock path**: concurrent `call_next` vs
  `operator_select`/`skip`/`recall_hold` from independent connections — exactly one
  selection wins, holds gate selection atomically, no lost holds. Real PostgreSQL 18,
  deterministic synchronization (see `docs/testing/evidence-authoring-guide.md`).

Open owner decisions:

1. The closed `operator_select` reason set (what values?).
2. Hold expiry: does `until_time` auto-release via a scheduled action, and who owns that
   schedule (queue, not `platform/scheduling` policy)?
3. Can multiple entries be held simultaneously, and does `skip` count-bound?
4. Does `operator_select` require an open `service_session` flow identical to
   `call_next`, and what happens to a selection if the room never opens?
5. Whether triage commands surface on the day board in the same slice or the board slice.
6. Capability strings and whether bot principals ever see them (default: no).
7. What a held entry looks like to the patient-facing queue status query
   (`queue/contracts/service_queue.py` `QueueStatus.entries_ahead`) — does a hold change
   the positions a waiting patient sees, and if so how, without lying?
8. Whether the reason set for `operator_select` is fixed globally or per deployment
   (§7 says closed set, no tenant-configurable policies — so likely fixed; confirm).

## 6. What this handoff could NOT verify

- The full lock-order documentation for `call_next` lives in `docs/v3/02-pre-sql-contract.md`
  and the queue module README; this handoff confirmed the lock path files exist but did
  not re-derive the canonical lock order — read them before touching selection SQL.
- Whether `until_event` conditions can be satisfied from existing queue/delivery events
  today or need a new condition source — no condition-evaluation machinery was found in
  the queue module while writing this; treat that as an open design item, not a fact.
- No PostgreSQL runner was executed while writing this handoff; all claims come from
  reading code, migrations and docs at commit `063332fc`.
