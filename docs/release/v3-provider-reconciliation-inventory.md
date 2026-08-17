# V3 ProviderEvent and communications reconciliation inventory

Status: Phase 6 G13 executable closure inventory. Exact implementation head `7ca60020608c9e153dcede578767ca9969b2f98f` passed canonical CI #960 with a `VALID` candidate artifact. G13 and R17/R18/R20/R21/R22 are `PASS` in the current registries; this registry-only reconciliation must itself pass canonical exact-head CI before PR integration.

Base for this closure: `development@cf98ac7da3b171d6dd42e0f77d91787b4450cc0c`.

This inventory closes provider/reconciliation reliability only for the capabilities Request Engine actually owns. It does not invent a universal provider callback state machine, does not promise exactly-once external delivery, and does not give ProviderEvent infrastructure direct Booking/Queue/Communications business authority.

## Ownership boundary

ProviderEvent is durable inbound transport evidence keyed by:

`(organization_id, provider_key, connection_key, provider_event_id)`.

The platform owns durable identity, payload fingerprinting, lease/retry/reject/dead/replay mechanics and routing to one explicitly configured `(provider_key, connection_key)` handler. It does **not** assign a universal semantic order to provider payloads. Provider-specific handlers must translate inbound facts into supported semantic application commands; those commands revalidate current aggregate authority, revision and lifecycle inside their authoritative transaction.

Communications owns a concrete provider-correlated delivery state machine and therefore has stronger platform-level reconciliation semantics of its own:

- `attempting`, `accepted` and `ambiguous` are nonterminal provider-correlated states that must reconcile before any new send;
- `delivered` is terminal and monotonic;
- a non-retryable `failed` result is also terminal for that Delivery and its CommunicationTask;
- a retryable `failed` result is provisional and may later recover to `delivered` if reconciliation proves the same provider attempt succeeded, because no terminal task-failure fact was emitted;
- a send exception is ambiguous, never proof that the provider did not accept the request;
- lookup infrastructure failure retries lookup work and never sends;
- provider `NOT_FOUND` after lookup becomes retryable failure and schedules a future dispatch according to policy;
- retryable provider failure schedules exactly one future dispatch for the failed Delivery attempt;
- every new send attempt receives a stable `provider_idempotency_key` derived from CommunicationTask + attempt number;
- authoritative post-provider state is published only after revalidating the exact current ScheduledAction claim;
- Request Engine promises duplicate resistance, durable correlation and reconciliation-first recovery, not exactly-once behavior from an external provider.

## A — ProviderEvent duplicate identity and payload conflict

`tests/integration/v3_worker_runtime/test_provider_event_ingest_races.py` deliberately overlaps independent app transactions on the same provider identity. Same identity + canonical-equivalent payload converges to one row and one replay receipt. Same identity + different payload raises `ProviderEventDedupeConflict` and preserves the first committed fact.

`tests/integration/v3_worker_runtime/test_provider_chaos.py` preserves the non-concurrent canonical-payload and terminal-state regressions. ProviderEvent terminal `rejected`/`dead` work cannot be reopened by stale worker finalizers.

This is the release proof family for R17.

## B — Provider callback reorder versus current business authority

There is no valid generic ordering rule such as `received < accepted < delivered` for arbitrary ProviderEvent payloads. Reorder safety is instead enforced at the semantic-command boundary.

`tests/integration/v3_reservation_lifecycle/test_provider_business_race.py` routes a real ProviderEvent handler into Booking's attendance command while Reservation cancellation races behind the same Reservation row lock. Both serialized winner orders are exercised. If the callback command wins, cancellation loses on revision. If cancellation wins, the stale provider command loses on revision/current lifecycle and cannot append attendance or retain capacity.

This is the release proof family for R18 and the generic ProviderEvent reorder rule: a late callback may be processed, but it cannot bypass current business authority.

## C — Communications send ambiguity

`tests/e2e/test_communication_worker_resilience.py::test_send_exception_becomes_ambiguous_and_schedules_lookup_not_resend` makes `provider.send()` raise after the call boundary. The Delivery becomes `ambiguous`, the dispatch action completes, exactly one future reconciliation is scheduled, and no new dispatch is scheduled.

A send exception is therefore never blindly retried as a new external effect.

## D — Communications reconciliation lifecycle

Existing E2E evidence proves:

- an ambiguous Delivery that later looks up as delivered completes the task without a second send;
- lookup infrastructure exceptions retry the same reconciliation ScheduledAction and preserve the provider-correlated Delivery state;
- crash after `prepare_dispatch` but before provider result persistence reclaims the original action and performs provider lookup before any resend;
- crash after provider finalization but before ScheduledAction acknowledgement reclaims the action and converges from durable Delivery/Task state without a second send.

`tests/e2e/test_communication_reconciliation_release.py` adds the missing repeated-accepted proof. A send returning `ACCEPTED` schedules one future reconciliation. A later lookup returning `ACCEPTED` schedules exactly one next reconciliation. A replayed dispatch while that future reconciliation exists performs lookup rather than send and does not fork another reconciliation chain. A later `DELIVERED` lookup terminalizes the same Delivery and emits exactly one completion event.

## E — Provider-result ordering and terminal monotonicity

`tests/e2e/test_communication_provider_result_ordering.py::test_delivered_result_is_monotonic_against_late_nonterminal_provider_results` finalizes one Delivery as delivered and then applies late `ACCEPTED`, `AMBIGUOUS`, retryable/non-retryable `FAILED`, and `NOT_FOUND` results. The Delivery must remain delivered, the task remains completed, exactly one completion event exists, no failure event appears and no future delivery/reconciliation work is created.

The G13 audit found the inverse terminal-order defect as well: two different `reconcile_delivery` ScheduledActions can both finish provider lookup for the same Delivery after separate prepare transactions. Before this branch, if the first lookup finalized `FAILED(non-retryable)` and emitted `communication.task_failed.v1`, a second lookup returning `DELIVERED` could overwrite the Delivery/Task and emit `communication.task_completed.v1`, leaving contradictory terminal business facts.

`tests/e2e/test_communication_terminal_reconciliation_race.py::test_two_reconciliations_cannot_emit_failed_then_completed_for_one_delivery` reproduces that actual interleaving with two claimed reconciliation actions and two provider lookups in flight. It forces the terminal failure to finalize first and releases the delivered result second. The second finalizer must observe the already-terminal non-retryable failed Delivery, return failed, leave the Task failed and preserve exactly one failure event with zero completion events.

The production rule is now explicit in `finalize_provider_result`: `delivered` and non-retryable `failed` are absorbing terminal states for the same provider attempt. `tests/e2e/test_communication_terminal_failure_ordering.py` preserves the direct regression. A retryable failed attempt remains recoverable: `test_retryable_failed_delivery_can_recover_from_late_delivered_evidence` proves later delivered evidence may complete it because the retryable failure emitted no terminal failure event; its already-scheduled future dispatch subsequently observes `task_completed` and becomes a no-op.

These are Communications-specific provider-result ordering rules. They complement R18 rather than replacing semantic-command authority for arbitrary ProviderEvents.

## F — Retryable/non-retryable provider failure and backoff

Existing E2E evidence proves a retryable provider failure returns the task to pending and schedules exactly one future dispatch, while a non-retryable failure marks the task failed and emits one failure event.

`tests/e2e/test_communication_reconciliation_release.py::test_crash_after_retryable_failure_finalize_cannot_bypass_future_dispatch_backoff` simulates a crash after the retryable Delivery result and future dispatch have committed but before the original action is acknowledged. After lease expiry/reclaim, the old action must resolve as `retry_already_scheduled`; it cannot send again, create another Delivery, or make the future retry due early.

`tests/e2e/test_communication_provider_result_ordering.py::test_reconciliation_not_found_schedules_backoff_dispatch_without_immediate_resend` proves provider `NOT_FOUND` is interpreted only after lookup: the same Delivery becomes retryable failed, the task returns pending and exactly one future dispatch is scheduled. No send occurs before that policy backoff boundary.

## G — Stale worker after provider I/O

`tests/integration/v3_worker_runtime/test_communication_fencing.py::test_worker_that_loses_lease_during_provider_io_cannot_finalize_delivery` forces lease replacement during `provider.send()`. The stale worker cannot publish delivered state. The replacement claimant performs provider lookup and finalizes the recovered result under the current claim with `send_count == 1`.

ReservationAccess independently demonstrates the same ownership principle for Outbox-driven provider provisioning in `tests/integration/v3_delivery/test_reservation_access_races.py`: stale Outbox work cannot publish ready access and replay reuses provider evidence instead of provisioning a duplicate resource.

Together with the crash-window E2E tests, this is the release proof family for R20.

## H — ProviderEvent failure, terminal states and operator replay

Worker semantics distinguish:

- `rejected`: semantically invalid provider work;
- `dead`: exhausted/permanent infrastructure or handler work;
- `processed`: successful handling.

Stale tokens cannot mutate terminal ProviderEvents. Application/worker roles cannot perform operator replay.

`tests/db/test_v3_provider_event_replay.py` exercises trusted admin replay for both `dead` and `rejected`: replay changes state to `received`, clears terminal/claim fields, preserves lifetime `attempt_count`, adds explicit attempt budget, increments replay history, makes the event due on the database clock and records actor/correlation/reason audit provenance. This is operational recovery, not automatic retry policy.

## I — Reminder occurrence reliability

ReminderPlan scheduling is part of Communications reliability rather than provider transport.

`tests/integration/v3_first_vertical/test_communications_reminders.py::test_reminder_occurrence_materialization_is_crash_replay_safe` proves sequential crash replay of the same leased occurrence converges to one CommunicationTask, one dispatch and one next Reminder occurrence.

`tests/integration/v3_first_vertical/test_reminder_occurrence_races.py::test_r21_duplicate_reminder_materialization_serializes_to_one_occurrence_graph` strengthens R21 with deliberate PostgreSQL overlap: two materializers for the same leased occurrence are both held behind the authoritative ReminderPlan `FOR UPDATE` lock, then released together. Both calls must return the same CommunicationTask/next occurrence and final state must contain exactly one Task, one dispatch, one next occurrence and one creation Outbox fact. The lease itself can be completed only once.

`tests/integration/v3_first_vertical/test_reminder_plan_races.py::test_r22_cancel_reminder_plan_vs_leased_occurrence_has_one_serialized_plan_outcome` deliberately overlaps cancellation and materialization behind the ReminderPlan lock. Cancellation-first produces no task; materialization-first may create exactly one current task before cancellation, but no future Reminder occurrence survives. This is the proof family for R22.

## J — ProviderEvent routing and poison work

`ProviderEventRouter` routes only to an explicitly configured `(provider_key, connection_key)` handler. Missing handlers are permanent worker failures rather than silent success. ProviderEvent worker rejection remains separate from dead-letter exhaustion.

Communications scheduled work likewise terminalizes unsupported action types, payload identity mismatch and missing provider configuration instead of retrying poison work forever. Existing E2E tests require domain failure state and failure-event cardinality where appropriate.

## Exact implementation evidence

Canonical CI #960 (`32067492021`) passed on exact implementation head `7ca60020608c9e153dcede578767ca9969b2f98f`: Python quality/architecture, observability, PostgreSQL 18 V2 history, repeated V3 bootstrap, V3 candidate proof and candidate-and-verticals all succeeded.

Artifact `v3-candidate-release-proof` `9300680212` (`sha256:d8cfb79d89f20dfac34bca906031bba5a6650011d6911b4d66c2befeca554839`) reports `evidence_status: VALID`, `artifact_set_complete: true`, zero validation errors and a clean tree. It binds base `cf98ac7da3b171d6dd42e0f77d91787b4450cc0c`, head `7ca60020608c9e153dcede578767ca9969b2f98f`, merge checkout/tested SHA `0e196a52b62e786e3d3200a9301f4be55e922f1d` and tree `d7c89c96a2e45ee4e8aaa6c4a67fa06a0edc3c92`.

All 115 expected test files were collected. The reverse-order run passed all 419 tests. Three concurrency-stability rounds each passed 82 tests. All four mutation probes were killed as expected. Test quality reported zero errors and zero warnings.

The artifact correctly remains `release_status: NOT_READY`; this proof closes the G13 provider/reconciliation and communications reliability family, not unrelated release gates.

## Promotion rule

G13 and R17/R18/R20/R21/R22 are `PASS` in the current registries because one exact implementation head proves all sections A-J through canonical CI and a `VALID` candidate artifact. Any later change that weakens ProviderEvent identity/routing, Communications provider-result ordering, reconciliation-first behavior, retry/backoff, stale-worker fencing, Reminder occurrence serialization or the named proof families invalidates the corresponding PASS until regenerated.

This registry-only reconciliation must itself pass canonical exact-head CI before PR #61 is merge-authoritative. Final promotion to `main` must regenerate the complete G13/race proof on the eventual frozen release candidate.

No promotion here changes global V3 `release_status: NOT_READY`. G05, G15-G20 and any other incomplete gate retain their current status.