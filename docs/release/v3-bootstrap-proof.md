# V3 candidate repeated-bootstrap proof

Status: Phase 6B proof contract.

## Purpose

`scripts/db/prove_v3_candidate_bootstrap.sh` proves that the current V3 candidate can be constructed twice from independently empty PostgreSQL databases in the same fresh PostgreSQL 18 CI cluster and produces the same normalized bootstrap inventory.

This is a candidate-construction gate. It is not the final schema fingerprint and it does not authorize creation of `0001_initial`.

## Procedure

The proof script:

1. creates two dedicated scratch databases using a restricted identifier prefix;
2. asserts that none of the four V3 application schemas exists before construction;
3. applies the complete ordered V3 candidate chain independently to each database;
4. verifies required schemas and `btree_gist` exist;
5. rejects application constraints left `NOT VALID`;
6. captures a normalized ordered inventory of application schemas, relations, columns, constraints, indexes, function signatures/properties, triggers, RLS policies and the required extension;
7. requires both inventories to be byte-identical;
8. destroys both scratch databases on exit, including failure paths.

The proof intentionally does not drop cluster-global Request Engine roles. The first construction in a fresh CI cluster exercises role creation; the second exercises idempotent reuse of those same cluster-global roles while still constructing a new empty database.

## Safety boundary

The script never drops `PGDATABASE`. It only creates and destroys `<V3_PROOF_DATABASE_PREFIX>_a` and `<V3_PROOF_DATABASE_PREFIX>_b`, and the prefix must be a simple PostgreSQL identifier.

CI uses `request_engine_v3_phase6` as the prefix.

## CI gate

`.github/workflows/ci.yml` runs this proof in `postgres-v3-bootstrap-proof` against PostgreSQL 18.

A configured job is not sufficient evidence. G04 may become `PASS` only after the current branch executes this job successfully.

## Deliberate limitation

The bootstrap inventory is narrower than the Phase 6C schema fingerprint. It does not yet prove normalized function bodies, role attributes/memberships, grants/default privileges, complete extension metadata, or every catalog property needed for candidate-versus-`0001_initial` equivalence.

Phase 6C owns that stronger fingerprint and catalog audit.