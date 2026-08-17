# Request Engine V3 — runtime privilege closure inventory

Status: Phase 6 runtime-privilege contract proven on the current branch. G14 is `PASS` for the current candidate evidence and must be regenerated on the eventual frozen release head.

## Security claim

Runtime credentials are not schema owners. Product/domain execution, worker control-plane execution and trusted operational administration have intentionally different PostgreSQL surfaces, and privilege drift must be detectable by executable catalog equality rather than by sample permission checks.

The frozen role model is:

```text
request_engine_schema_owner  NOLOGIN  NOBYPASSRLS  owns schema objects only
request_engine_app           NOLOGIN  NOBYPASSRLS  domain/application runtime
request_engine_worker        NOLOGIN  NOBYPASSRLS  control-plane worker runtime
request_engine_admin         NOLOGIN  BYPASSRLS    trusted operational administration
```

Production-style LOGIN roles inherit exactly one of those group roles. A LOGIN starts `NOBYPASSRLS`; an authorized admin credential may explicitly `SET ROLE request_engine_admin` to enter the trusted BYPASSRLS surface. App and worker credentials must not be able to enter admin or schema-owner authority. No runtime group role has `CREATE` on Request Engine schemas or owns authoritative relations/functions.

## Application surface

`request_engine_app` may:

- use `request_engine`, `request_read` and `request_cmd`;
- read/insert/update tenant-local authoritative tables subject to RLS and application policy;
- read versioned `request_read` views;
- execute the explicit application primitives needed for idempotency, Party authority, ScheduledAction cancellation/claim fencing, Outbox claim fencing and shared-capacity locking.

It may not:

- use `request_admin`;
- read or mutate private cross-tenant identity/shared-capacity control-plane tables;
- delete/truncate/trigger/maintain authoritative tables;
- create schema objects;
- become worker/admin/schema-owner.

The exact function surface is frozen by `tests/db/test_v3_app_function_privilege_inventory.py` and the complete three-role matrix in `tests/db/test_v3_runtime_privilege_closure.py`.

## Worker surface

`request_engine_worker` is control-plane only. Production Worker Assembly routes domain handlers through a separate `request_engine_app` session, so the worker credential needs no direct authoritative table/query surface and no domain idempotency or Party-authority functions.

Migration `038-runtime-privilege-closure.sql` removes stale historical grants for:

- `request_cmd.acquire_idempotency`;
- `request_cmd.complete_idempotency`;
- `request_engine.resolve_current_party_authority`;
- `request_engine.lock_current_party_authority`;
- `USAGE` on `request_read`.

The remaining worker function surface is limited to ScheduledAction/Outbox/ProviderEvent claim, lease, fencing, retry/finalization controls plus the runtime context helpers required by the worker boundary. Worker has no direct relation privileges in `request_engine`, `request_read` or `request_admin`.

## Admin surface

`request_engine_admin` is a trusted operational role rather than a product runtime role. Its BYPASSRLS attribute is intentional and must not leak to app/worker credentials.

An authorized admin credential may explicitly assume `request_engine_admin` and use:

- operational/admin replay and shared-capacity authority functions;
- worker control functions;
- diagnostic `request_admin` views;
- administrative relation access defined by the candidate.

It may not become `request_engine_schema_owner`, create objects in Request Engine schemas, or own/replace authoritative routines. Private cross-tenant identity/shared-capacity tables remain read-only to admin except through the audited `request_admin.*` authority functions.

## SECURITY DEFINER closure

Every `SECURITY DEFINER` routine in `request_engine`, `request_cmd` or `request_admin` must satisfy all of the following dynamically over the complete catalog:

1. owner is `request_engine_schema_owner`;
2. `search_path` is exactly `pg_catalog, request_engine, pg_temp`;
3. `PUBLIC` has no `EXECUTE`;
4. any app/worker/admin caller access is present only through that role's exact reviewed function allowlist;
5. runtime roles cannot replace the function or create shadow objects in trusted schemas.

A new `SECURITY DEFINER` therefore automatically enters the audit even if it is private to triggers. A new runtime-executable function additionally fails the exact role function surface until the inventory is intentionally updated.

## Complete relation matrix

The executable proof enumerates every table/view/materialized view in the application schemas for each real LOGIN and compares effective privileges to the intended role policy:

- app: tenant-local `SELECT/INSERT/UPDATE`, versioned reads, no private global tables;
- worker: no direct relations;
- admin: trusted administrative relation surface, with private global tables remaining read-only;
- `request_admin` views: admin only;
- `request_read` views: app/admin only.

This complements the existing future-object/default-privilege probe in `test_v3_runtime_privilege_contract.py`.

## Exact-head evidence

CI #914 (`32034507295`) on head `90529b199064924561b61da5e2611d3c1ffdb78f` produced artifact `9290385131` with digest `sha256:2b79a0fb702cb3f601bf80f68706eb8b30a2d5a97f0069c2950ff07d34de2f73`. The artifact is `VALID`, complete, clean-tree evidence bound to tree `100d55c00f32e389ae4930fb0af3e54838efba58`.

The canonical suite collected 396 tests from all 104 expected files, passed 396/396 in canonical and reverse order, completed three concurrency-stability rounds of 70/70 tests, passed all four mutation probes and reported zero test-quality errors or warnings. The G14 matrix itself passed for real app, worker and admin LOGINs plus the complete dynamic `SECURITY DEFINER` audit.

The same candidate run proved migration 038 did not break the worker/domain split after removing the stale historical worker grants. During this closure, an unrelated test-corpus time bomb was also exposed: SlotOffer/shared-capacity fixtures used a booking date that became historical on 2026-08-17. Those tests now use a deterministic far-future Monday while preserving the same weekday/local-time semantics; no production expiry rule was relaxed.

## Exit conditions

G14 is `PASS` on the current branch because one exact head proves all of the following:

1. migration 038 applies and repeated bootstrap remains green;
2. real app/worker/admin LOGINs match the complete schema/relation/function matrices;
3. app/worker cannot acquire BYPASSRLS or `SET ROLE` into admin/schema-owner;
4. admin BYPASSRLS is reachable only through its explicit trusted admin role and still cannot perform owner DDL;
5. every current `SECURITY DEFINER` satisfies owner/search-path/PUBLIC hardening;
6. canonical candidate, reverse-order, concurrency-stability and mutation evidence is `VALID`.

This phase changes no product capability, does not freeze indexes and does not create or bless `0001_initial`.
