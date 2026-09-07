# PostgreSQL baseline

This directory is the canonical, immutable payload for Request Engine Alembic revision `0001_initial`.

It was materialized from the audited PostgreSQL 18.6 effective model produced by current-product CI #4164 at `4ba7dbf092528f26aee5db1003af455a381d3431`, then promoted only after clean-cluster, exact-role and single-Alembic reproduction proofs were green. Final repository cleanup is validated independently by normal current-product CI.

`manifest.json` records the complete schema checksum, per-part checksums, the six-role bootstrap topology and accepted baseline counts. `loader.py` verifies those checksums and the exact role contract before `0001_initial` executes the SQL.

The baseline contract is intentionally different from the current Alembic head contract:

- `migrations/baseline/` and `0001_initial` are immutable accepted history;
- future schema evolution appends `0002+` revisions under `migrations/versions/`;
- current-product CI upgrades to the repository head and proves current invariants;
- baseline-integrity CI separately proves that the accepted `0001` still installs from a clean PostgreSQL 18 cluster.

Do **not** regenerate or edit this payload to make a later migration easier. If the product evolves, add a new Alembic revision. A future destructive rebaseline would require a new explicit audit and proof cycle rather than silently rewriting this directory.

The original `rebaseline-candidate.sql` and `rebaseline-role-bootstrap.sql` names retained in `manifest.json` are provenance identifiers for the CI artifacts from which this accepted payload was materialized; they are not active repository paths or candidate status.
