# Request Engine — Greenfield validation and data premise

Status: development/validation premise for the current post-V3 feature work.

This note clarifies the deployment state assumed while implementing and proving
`feature/operational-profile-contextual-supply` and the immediately following
pre-production features.

## Current reality

Request Engine is not operating against a production database with customer or
business records. There is no live tenant data, Reservation history, commercial
history, operational configuration, or other customer-owned state that must be
preserved by a one-time data migration today.

The databases created by CI and local development are disposable proof
environments populated only with fixtures and synthetic test data. Their
purpose is to falsify schema, transaction, authorization, concurrency,
compatibility, and product invariants before Request Engine begins storing real
customer data.

## What this permits

Because the project is still greenfield with respect to real data, feature work
must not invent migration complexity solely to preserve nonexistent production
rows. In particular, we do not need a customer-data backfill campaign, staged
online migration, dual-write cutover, or historical repair process merely to
support hypothetical records that have never existed outside tests.

When an invariant can be expressed more cleanly for the production schema we
intend to launch, prefer the clean design, subject to the immutable V3 baseline
and append-only migration-history rules already established by the project.

## What this does not permit

"No production data yet" does **not** mean that compatibility proofs may be
removed or weakened. The repository still has a released V3 baseline and its
contracts are architectural history that F1 must extend safely.

Therefore CI must continue to prove at least:

- clean bootstrap of the production-head schema;
- deterministic upgrade from checked-in `0001_initial` through all post-V3
  Alembic revisions;
- frozen V3 candidate equivalence against `0001_initial`, where that historical
  proof explicitly targets the V3 revision rather than the current F1 head;
- released V3 booking, shared-capacity, tenant-isolation, worker and other
  compatibility behavior unless an explicit post-V3 contract intentionally
  replaces it;
- repeatable bootstrap and schema/catalog assertions;
- F1 authorization, stale-option, contextual-supply, schedule, price/history,
  concurrency and shared-capacity invariants.

Synthetic fixtures that represent legacy V3 state remain valuable because they
prove compatibility of the code and schema. They must not be mistaken for an
obligation to preserve real customer records that do not exist yet.

## Future transition

This premise expires the moment Request Engine begins holding real production
customer data. From that point forward, every schema or semantic change must
consider actual persisted data, rollout sequencing, backward/forward
compatibility, recovery, and migration safety as production concerns.

Until then, the priority is to make the first production schema and behavior
correct, deterministic, secure, testable, and internally coherent rather than
to accumulate migration machinery for hypothetical data.
