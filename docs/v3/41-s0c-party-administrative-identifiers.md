# S0c — Party administrative identifiers

Status: normative contract for the S0c prerequisite to the remaining front-desk slices.

## Purpose

A tenant-owned `Party` may need exact administrative resolution keys that are not identity
documents. The first supported kind is `insurance_member`: a member/policy identifier issued
by an insurer or ARS.

This capability does **not** make Request Engine an insurance eligibility, claims or billing
system. It stores only the identifier needed to resolve the local Party.

## Ownership and privacy boundary

Administrative identifiers belong to the same `organization_id` as the Party. RLS is enabled
and forced. No lookup may reveal whether another organization has the same identifier.

Two independent organizations may therefore store the same `(kind, issuer, value)` for their
own local Parties. Clinics that are one operational business and intend to share patients
should be modeled as locations under one organization rather than separate organizations.

Cross-organization patient discovery, profile reuse, merge or federation is explicitly out of
scope. Such a feature would require its own consent, disclosure and governance contract.

## Identity versus administrative identifiers

Government identity documents remain in `party_identity_documents`; Dominican cédulas are
stored in full and normalized to the exact 11-digit value for tenant-local lookup.

`party_administrative_identifiers` stores third-party identifiers with:

- `kind` — currently only `insurance_member`;
- `issuer` plus `normalized_issuer`;
- the original `value` plus `normalized_value`;
- durable attribution (`created_by_principal_id`, `source_kind`, `platform`, relay principal);
- active state and timestamps.

Issuer is part of identity. A member number from ARS A is not assumed to identify the same
record as the same characters from ARS B.

## Uniqueness and duplicate policy

For active rows, one Party may have at most one identifier per `(kind, issuer)`, and one exact
`(kind, issuer, normalized_value)` may belong to at most one Party inside an organization.
Database unique indexes are the concurrency backstop; application pre-checks are not treated
as sufficient authority.

Normal intake is lookup-first:

1. exact local cédula lookup when a cédula is supplied;
2. exact local administrative-identifier lookup when an insurer/member ID is supplied;
3. if found, reuse the existing Party and add/correct local contact facts through their owner
   capabilities;
4. if not found, create a new local Party;
5. phone/name similarity may produce a review candidate but must never silently merge records.

A generalized Party merge remains a separate explicit workflow. Exact same-tenant cédula and
administrative-identifier uniqueness prevents new duplicates through the supported registry;
historical duplicates must not be silently collapsed.

## HTTP surface

- `POST /v1/parties/{party_id}/administrative-identifiers`
  - capability: `parties.add_administrative_identifier`
  - idempotency required
- `GET /v1/parties/{party_id}/administrative-identifiers`
  - capability: `parties.lookup_administrative_identifier`
- `GET /v1/parties/lookup/administrative-identifier?kind=...&issuer=...&value=...`
  - capability: `parties.lookup_administrative_identifier`
  - returns zero or one tenant-local Party

Neither administrative-identifier capability is part of the documented bot grant subset.
Front-desk operators may receive them explicitly; a channel integration does not inherit them
from `parties.register` or `parties.lookup`.

## Persistence and failure semantics

Facts (`party_id`, kind, issuer and value) are immutable after insert; future retirement may
toggle `active`. The command is transactional and idempotent. Concurrent insertion is resolved
against database uniqueness: an identical row on the same Party is stable, while ownership by
another local Party returns a typed conflict carrying the existing local Party id.

## Proof obligations

Current-product proof must cover:

- normalization of kind, issuer and member value;
- stable idempotency replay;
- same-tenant conflict with the existing Party id;
- cross-tenant invisibility under the runtime app role;
- the same insurer/member value being valid independently in two organizations;
- capability/grant isolation so the existing bot subset implies neither administrative-
  identifier write nor read capability.
