# Handoff 07 — Open Decisions, Technical Debt and First-Deployment Checklist

Status: honest backlog, verified against the repo at `development` merge `a8760d9f`
(working tree Sep 2026). Companion: `docs/handoff/00..06`.

## 1. OWNER DECISIONS PENDING

Each item: the question, the context, and the current default/recommendation.

1. **Cédula checksum validation.** Question: should RE validate the check digit of a
   Dominican cédula, or is format-level validation enough? Context: today
   `party_identity.py:73` enforces exactly 11 digits and nothing more. Default: keep
   11-digits-only for the pilot (typo-tolerant registration beats a hard rejection at
   the front desk); revisit if bad documents pollute lookups.
2. **Cédula masking for bot-facing lookup.** Question: should `parties.lookup` return
   full government IDs to bot principals? Context: bots hold exactly
   `parties.register`/`add_contact_point`/`lookup` (`docs/v3/38` §5), and the lookup
   view returns documents with the full `normalized_value`
   (`party_registry_models.py:81-99`) — so a bot can read full IDs today. This is a data
   minimization question, not an authorization bug. Default/recommendation: mask or omit
   document values in bot-scoped lookup responses before real patients flow.
3. **Party merge.** Question: when do we build an explicit merge command? Context:
   deliberately deferred — merge/split are "intentionally not supported operational
   workflows in this version" (`docs/adr/0011` line 61) and silent merge is an anti-goal
   (`docs/v3/38` §7). Deactivate + re-register covers the pilot. Default: stay deferred;
   revisit only if duplicate parties accumulate in practice.
4. **Rename history surface.** Question: does the operator need a UI for name-change
   history? Context: the audit trail already exists — every party mutation appends a
   full-identity revision to the append-only `party_identity_revisions` ledger, and
   `parties.read_revisions` is a registered capability (`modules/tenancy/README.md`
   lines 11-31). Default: none for the pilot; the ledger is queryable if ever needed.
5. **Fatigue counting interpretation.** Question: is "count tasks created today for the
   recipient, across all lineages and purposes, on the database day" the intended
   reading of the `docs/v3/36` §4 fatigue guard? Context: that is exactly what is
   implemented and documented (`escalation_next_channel.py:105-110`,
   `modules/communications/README.md:92-94`). Default: keep; it is conservative
   (counts ALL outbound intents, not just escalations).
6. **Prepare-side delivered-upgrade disposition.** Question: confirm you accept that a
   late authenticated `delivered` report may complete a failed-and-escalated task while
   its escalation child is still live. Context: accepted behavior, dispositioned in the
   `docs/v3/40` "Review dispositions" (lines 122-126): delivered-upgrade-not-downgrade
   preserves the contract; the child's own outcome reconciles independently. Default:
   accept as documented.
7. **Which day-1 inbound intents are automatable.** Question: of the inbound messages a
   patient sends (reschedule me, I'm late, cancel, question…), which become automated
   RE commands versus always human? Context: S4 inbound interpretation is explicitly
   deferred (`docs/v3/40` "Explicitly deferred", line 150); nothing reads a patient's
   WhatsApp today (`docs/handoff/01` §4). Default: no inbound automation until S4 +
   the gateway conversation adapter exist.
8. **Deployment choices.** Question: who hosts the gateway (§ handoff 06), and how do we
   obtain WhatsApp Business API (Cloud API) access for the Dominican Republic — direct
   Meta, or via a BSP? Context: no hosting, no Meta account, no phone number exist in
   the repo or anywhere. Default: none — this is the blocking external procurement
   decision for the first clinic.

## 2. TECHNICAL DEBT (verified, with paths)

- **Ratcheted oversized files.** The file-budget rule
  (`scripts/ci/check_python_file_budget.py`, hard max 120 effective lines) allows legacy
  oversized files to exist but never grow. Measured effective lines:
  `modules/communications/adapters/db/delivery_store.py` = **674**; several e2e test
  files are also over budget (`tests/e2e/test_multi_user_journeys.py` 531,
  `test_communication_worker_resilience.py` 488, `test_communication_delivery_lease_fence.py`
  398, `tenant_sandbox.py` 322, `http_surface.py` 318). New code must go into NEW files;
  these may only shrink.
- **Duplicate OpenAPI operation-id warning (pre-existing).** `add_capability_route`
  derives `operation_id` from the capability key (`platform/http/capability_routes.py:49`),
  and two staff-contact routes share the capability `staff.manage_own_admin_contact`
  (`modules/tenancy/api/staff_contact_routes.py:104-120`) — so both schema entries get
  `staff_manage_own_admin_contact` and the OpenAPI build warns about the duplicate.
  Harmless but noisy; fix = pass an explicit `operation_id` for one of the two routes.
- **Guarantee registry is representative, not exhaustive.** S0b proofs are registered
  (`INV-CONTACT-VERIFICATION-001`, three proofs under
  `tests/integration/s0b_party_registry/` in `docs/testing/current-proof-map.toml:663-675`),
  but the map's 133 entries still lean on feature-era suites (F1/F3 etc.) and the file
  itself states it is migration evidence, `normative = false`. Earlier F-slice coverage
  is partial/representative: do not treat the map as a complete proof inventory.
- **3 Windows-SIGKILL crash tests cannot run on the owner's machine.**
  `tests/integration/v3_worker_runtime/test_process_crash_recovery.py:75` and
  `test_process_crash_recovery_other_families.py:190` (parametrized over outbox +
  provider_event = 3 test items) kill a real child process with `signal.SIGKILL`, which
  does not exist on Windows; there is no skip marker, so they fail locally on Windows and
  only pass on Linux CI. This is a known local-runner gap, not a code defect.
- **`docs/v3/37` slice sections S1-S6 are pre-reorder history.** The original build
  order (lines 22-146) was superseded by the round-3 usability audit (line 148 onward),
  which is "registered as authoritative for slice ordering" (S0b → S3 → day board → S5
  → S4 → S6, lines 178-180). Read S1-S6 for slice content, never for order.

## 3. DEPLOYMENT CHECKLIST — first clinic

Brutal baseline: **nothing is deployed today** — no server, no gateway, no WhatsApp
number, no tenant has ever received a message (`docs/handoff/01` §4). Before any real
message flows, someone must:

1. Provision **PostgreSQL 18** and run the migrations (immutable `0001_initial` plus the
   append-only revisions that follow it).
2. Run the worker with the reference factory (`REQUEST_ENGINE_WORKER_FACTORY =
   request_engine.bootstrap.reference_worker_factory:create_worker`) and set every
   required variable from the env contract (`docs/v3/10` lines 225-234):
   `REQUEST_ENGINE_WEBHOOK_BASE_URL` (HTTPS), `REQUEST_ENGINE_WEBHOOK_AUTH_HEADER`
   (form `Header-Name: value`), `REQUEST_ENGINE_WORKER_DATABASE_URL` and
   `REQUEST_ENGINE_APP_DATABASE_URL` (the two distinct roles — one is NOT a substitute
   for the other), `REQUEST_ENGINE_WORKER_PRINCIPAL_ID`, and
   `REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY` — remember there is no default publisher;
   someone must write/wire one or startup fails.
3. Expose the authenticated provider-event callback endpoint to the gateway and point the
   webhook auth header at the same secret on both sides (single static header today —
   see handoff 06 §7 risks).
4. Create the bot principal the gateway authenticates as, granted exactly
   `parties.register`, `parties.add_contact_point`, `parties.lookup` (`docs/v3/38` §5);
   and decide the **operator capability source for the relay** — staff actions relayed
   through the bot layer must arrive as an authenticated operator principal or an
   explicit operator override contract, never free-text trust assertions
   (`docs/v3/38` §5, end).
5. **Build the gateway** (handoff 06 §6 build order). Until at least steps 1-3 of that
   order exist, the whole communications loop is dead ends: RE can enqueue intents and
   nobody receives anything.
6. Decide the external items from §1.8: gateway hosting and WhatsApp Business API access
   for the DR.

Nothing above has been done. Each completed step should be recorded here or in the
day board when it actually happens.

## 4. Verification notes for this document

Every file/line claim above was checked against the working tree on 2026-09-01
(branch `feature/handoff-docs`, base `development` merge `a8760d9f`). Two caveats:

- `delivery_store.py` measures 674 effective lines today; an earlier note said 673.
  The ratchet property (may not grow) is what matters, not the exact number.
- The WhatsApp/DR procurement question (§1.8) and gateway hosting have no repository
  evidence to verify against by definition — they are recorded as owner decisions, not
  repo facts.

Checks run for this document: `python scripts/ci/check_documentation_contract.py
--base origin/development` (pass) and `python scripts/ci/check_python_file_budget.py
--base-ref origin/development` (pass). These validate documentation routing and the
Python file budget only; they are not product proofs.
