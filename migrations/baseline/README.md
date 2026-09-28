# PostgreSQL baseline

This directory is the canonical, immutable payload for Request Engine Alembic revision 0001_initial.

The current baseline was materialized from the audited PostgreSQL 18.6 effective model at historical Alembic head 0094_managed_oidc_readiness and commit 3e938a888e576919b5b75f449fe86014b5cbd7f9. GitHub Actions run 36354361866 proved the promotion gates before the historical chain was removed:

1. 0001 through 0094 installed successfully on PostgreSQL 18;
2. the candidate reproduced all six managed schemas and the ten-role topology;
3. the candidate reproduced the exact PostgreSQL DDL byte-for-byte;
4. the candidate reproduced all migration-owned seed/reference rows and sequence state;
5. the candidate installed by itself on a completely clean PostgreSQL 18 cluster and passed the same equivalence checks.

manifest.json pins the complete payload checksum, every materialized part, the ten-role bootstrap topology, the seed/reference-state checksum, accepted effective-model counts and the proof provenance. loader.py verifies those checksums and exact managed-role contract before 0001_initial executes the SQL.

After this rebaseline, migrations/versions/0001_initial.py is the only historical revision. Future schema evolution appends new 0002+ revisions. Never regenerate this payload merely to make a later migration easier; another destructive rebaseline requires a new explicit audit and clean-cluster equivalence proof.
