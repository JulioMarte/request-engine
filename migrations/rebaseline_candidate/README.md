# PostgreSQL rebaseline candidate

This directory contains the reviewed pre-production replacement baseline payload for Request Engine.

The schema SQL is the exact PostgreSQL 18.6 schema-only artifact produced by current-product CI #4164 from `cohesion/system-optimization@4ba7dbf092528f26aee5db1003af455a381d3431`. `manifest.json` records the complete payload checksum, per-part checksums, audited role topology and effective-model counts.

The active migration line on this candidate branch intentionally contains only `migrations/versions/0001_initial.py`. That revision:

1. requires a database with no existing Request Engine application schemas;
2. verifies and bootstraps exactly the six audited `request_engine_*` roles;
3. verifies every materialized SQL part and the reconstructed payload SHA256;
4. executes the reviewed schema through Psycopg's simple-query protocol;
5. leaves Alembic to record `0001_initial` after successful schema creation.

This directory is not historical migration archaeology. It is the reviewable source payload for the current product model. The old `0002..0050` chain must remain outside the active line once this candidate is accepted; its provenance remains available in Git history.

Acceptance requires normal pull-request CI against `development`, clean PostgreSQL 18 bootstrap, exact schema/role catalog equivalence to the audited 99-relation model, and the complete current-product proof with no gaps.
