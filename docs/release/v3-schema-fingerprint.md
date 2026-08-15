# V3 schema fingerprint and catalog audit

Status: Phase 6C proof contract.

## Purpose

Phase 6C creates a deterministic representation of the V3 PostgreSQL contract that is stronger than the Phase 6B bootstrap inventory.

The fingerprint exists primarily for the later 6N equivalence proof:

```text
candidate chain fingerprint == 0001_initial fingerprint
```

Passing application tests alone is not sufficient to establish structural equivalence.

## Fingerprint surface

`scripts/db/v3_schema_fingerprint.py` serializes normalized catalog facts without PostgreSQL object OIDs. The format currently includes:

- application schemas and owners;
- Request Engine runtime/schema roles and role memberships;
- relations, ownership and RLS flags;
- columns, types, nullability, generated/identity state and defaults;
- sequences;
- application enum/domain types;
- constraints and validation state;
- indexes and validity/readiness state;
- view definitions;
- function signatures, properties, local settings and normalized definitions;
- triggers;
- RLS policies;
- required extension metadata;
- effective schema/relation/function/type ACLs;
- relevant default privileges.

The canonical payload is compact sorted JSON. `SHA-256` over those bytes is the schema fingerprint.

The payload records the PostgreSQL major version because catalog normalization is a release-format contract, not a promise that fingerprints remain identical across PostgreSQL major versions.

## Catalog audit

`scripts/db/audit_v3_catalog.py` separates release-blocking errors from review warnings.

Release-blocking catalog errors currently include:

- application constraints left `NOT VALID`;
- invalid or not-ready application indexes;
- tenant relations with `organization_id` but no RLS enabled;
- `SECURITY DEFINER` application routines without a function-local `search_path`;
- PUBLIC privileges on application schemas, relations or routines;
- missing or unsafe attributes on the four explicit Request Engine roles.

Warnings currently identify:

- tenant relations with RLS enabled but no explicit policy;
- foreign keys with no matching leading-column index;
- indexes that appear structurally duplicated.

A warning is not automatically a defect. Phase 6 must review it and either create a measured fix or document why the shape is intentional.

## Security rationale

The audit does not treat `SECURITY DEFINER` as inherently unsafe. It requires those routines to pin `search_path`, because untrusted name resolution is unacceptable at a privilege boundary. Runtime app and worker roles remain `NOBYPASSRLS`; the explicit admin role is the only Request Engine baseline role expected to use `BYPASSRLS` for narrow administrative surfaces.

## CI

The PostgreSQL 18 V3 candidate job generates:

```text
.phase6/v3-schema.json
.phase6/v3-schema.sha256
.phase6/v3-catalog-audit.json
```

The fingerprint and audit execute after candidate construction and before the full PostgreSQL vertical suite. The release artifacts are uploaded even when a later test fails.

G05 remains `PARTIAL` after this tooling lands because the complete invariant/race proof belongs to later Phase 6 work. The fingerprint itself does not prove behavioral correctness.