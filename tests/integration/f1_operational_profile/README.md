# F1 operational-profile test ownership disposition

Status: current-product evidence retained during feature promotion.

This directory exists because F1 was developed as one coherent integration slice. It is **not** a permanent feature-era taxonomy. The following disposition applies when F1 is integrated into `development`:

- public production-like journeys belong in `tests/e2e/` and are being added there now;
- PostgreSQL constraint, temporal, race, lock-order, provenance, capacity and tenant-isolation proofs are durable current-product evidence and should move to `tests/db/` when the move can preserve fixture clarity without weakening the proof;
- pure module/application behavior should move under the owning `tests/modules/<module>/` tree when it no longer requires the shared cross-module F1 world;
- `dummy_data.py` remains feature-local while this suite is one integration world; it must move to `tests/fixtures/` only if independent durable suites genuinely share it;
- no F1 test becomes `historical` merely because this branch merges. `tests/historical/` is reserved for pinned released provenance;
- no proof may be removed during the ownership move without KEEP / ADAPT / REPLACE / REMOVE / HISTORICAL disposition tied to the guarantee it protects.

The physical move is intentionally separated from semantic promotion: first establish equivalent durable public/control-plane E2E coverage and preserve all current PostgreSQL evidence, then relocate files without changing their assertions. This avoids combining namespace churn with behavior changes and preserves exact failure attribution.
