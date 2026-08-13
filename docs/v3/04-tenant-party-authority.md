# V3 tenant and Party authority convergence

Status: normative pre-baseline clarification for DB-06 / DB-07.

## 1. Distinct identities

Request Engine keeps these concepts separate:

```text
Organization = hard tenant root
Principal    = authenticated technical actor identity
Party        = business identity/subject
Representation = material delegated authority for a Principal to act for one Party in one scope
```

Authentication of a Principal does not imply authority over any Party. A phone number, email address, Request participant role, external correlation or possession of a Party UUID is never authority by implication.

## 2. Two explicit authority paths

A subject-scoped command may be authorized by exactly one of these policy paths:

1. **delegated Party authority** — a current Representation proves the Principal may act for the Party in the required scope;
2. **operator authority** — command policy explicitly permits a tenant operator/staff Principal to act for arbitrary Parties under a separately granted operator permission.

Operator authority is not materialized as a fake Representation. The audit record must preserve which path authorized the command.

RLS only proves tenant isolation. It does not prove same-tenant Party authority.

## 3. Representation semantics

Baseline Representation fields include:

```text
principal_id
represented_party_id
authority_kind
scope_key
status
valid_from
valid_until?
revision
```

`authority_kind` is provenance, not a permission hierarchy. Baseline values are:

```text
self
guardian
authorized_contact
delegated
```

`scope_key` is an exact namespaced application-policy key. V3 baseline does not define wildcard matching, scope inheritance or an authorization DSL.

Examples may include:

```text
appointments.manage
queue.manage
requests.submit
reminders.manage
```

The owning command defines the exact scope it requires.

## 4. Revocation and expiry have one source of truth each

Persisted Representation status is:

```text
active | revoked
```

Expiration is temporal and derived from `valid_until`; there is no persisted `expired` status.

A Representation is current iff all of the following are true at PostgreSQL wall clock time:

```text
representation.status = active
representation.valid_from <= db_now
representation.valid_until IS NULL OR representation.valid_until > db_now
principal.active = true
represented Party.active = true
```

This avoids dual truth where `status='active'` conflicts with an elapsed validity interval or `status='expired'` conflicts with a future `valid_until`.

## 5. Read resolution versus mutation linearization

V3 exposes two database-owned authority surfaces with the same exact-scope validity semantics but different concurrency behavior.

### Read-only resolution

`request_engine.resolve_current_party_authority(...)` performs a non-locking authority read. Queries such as Request/Queue/Reservation status may use this surface because they do not commit a subject-scoped business mutation.

### Mutation-time resolution

`request_engine.lock_current_party_authority(...)` resolves the same current Representation and acquires `FOR SHARE` row locks on:

- the Representation;
- the authenticated Principal endpoint;
- the represented Party endpoint.

The function is `SECURITY INVOKER`; tenant RLS remains in force.

This defines the mutation authority linearization point. Once a command has acquired these locks using a Representation that is current at PostgreSQL wall-clock time, a concurrent Representation revoke or Principal/Party deactivation must serialize after that command. The authorized command may finish; the subsequent revoke/deactivation governs later commands.

The baseline does not attempt to retroactively invalidate a transaction merely because `valid_until` passes between authority resolution and commit. Temporal validity is evaluated at the database instant when authority is established.

Using the non-locking resolver from a mutation is incomplete because `READ COMMITTED` alone does not stop this race:

```text
T1 resolve Representation = active
T2 revoke Representation + commit
T1 write subject-scoped mutation + commit
```

Mutation adapters therefore use the locking surface; read adapters explicitly remain on the non-locking resolver.

## 6. PostgreSQL versus Python ownership

PostgreSQL proves structural facts:

- Principal, Party and Representation belong to the same Organization;
- Representation validity interval is well formed;
- authority kind/status values are valid;
- tenant-local foreign keys cannot cross Organization boundaries;
- RLS prevents runtime cross-tenant access;
- mutation-time Representation/revoke ordering can be serialized through the locking authority primitive.

Python owns command policy:

- which Party is the subject of the command;
- which exact scope is required;
- whether an operator override is allowed for that command;
- whether a use site is a query or mutation and therefore which authority surface it consumes;
- how a resolved Representation or operator grant is recorded in audit provenance;
- denial behavior and public error mapping.

PostgreSQL must not become a universal RBAC/policy language.

## 7. Tenant-local FK invariant

For two tenant-owned tables that both contain `organization_id`, any relational FK between them must carry `organization_id` on both the source and target side.

Allowed exception: direct FK to the `organizations` tenant root itself.

Soft polymorphic references (`kind + id`) are allowed only for provenance/correlation where referential existence is not a business invariant. If a reference participates in authorization, capacity, lifecycle or money invariants, it requires a typed tenant-scoped relational FK.

## 8. Connection-surface requirement

Every subject-scoped command surface must state:

```text
subject Party source
required authority scope
whether operator override exists
representation/operator provenance written to audit
same-tenant structural proof
failure code when authority is absent
mutation-time authority locking behavior
```

A new subject-scoped API is incomplete until this connection is tested.
