# S0d — Federated Party identity adoption

Status: normative design and implementation contract stacked on S0c.
Owner module: `tenancy`.
This contract supersedes the older "no cross-clinic matching" assumption in `docs/v3/38` §9.4;
clinical/operational tenant isolation remains unchanged.

## 1. Purpose

Independent organizations keep independent tenant-owned `Party` records. A patient may choose to
reuse a small allowlisted set of identity/contact facts already supplied elsewhere. S0d models
**exact match + consented adoption**, never cross-organization Party merge.

A government identity document is an equality signal. Possessing or knowing its number is not
authorization to read another tenant's data.

## 2. Hard privacy boundary

- `Party`, appointments, queue/service history, communications, payments and clinical facts never
  move between organizations.
- Match never returns source organization, source Party id, name, phone, insurer or other PII.
- The destination always creates its own local Party.
- The destination captures the witnessed identity document again; raw document values are never
  copied from the portable profile.
- Portable data is opt-in and field-scoped.
- Raw bot/integration principals cannot assert an in-person document witness.

## 3. Proof admitted in this tranche

The first admitted proof is `operator_document_witness`:

1. an authorized human operator sees the patient's identity document;
2. the operator enters document kind, issuing authority and value;
3. the patient explicitly agrees to the requested portable fields;
4. Request Engine records the effective operator, proof kind and consented fields.

Remote subject verification remains unsupported until a real channel-possession or equivalent
identity proof exists. The API fails closed rather than inventing one.

## 4. Scoped identity document key

The canonical identity-document key is:

```text
(kind, authority, normalized_value)
```

Initial strong-document allowlist:

```text
cedula   | DO:JCE | normalized 11-digit cédula
passport | <ISO-3166 alpha-2 issuing country> | normalized passport number
```

Examples:

```text
cedula   | DO:JCE | 40212345678
passport | DO     | SC1234567
passport | US     | SC1234567
```

The two passport examples are deliberately different identities even though the number is equal.
A passport therefore never matches without an issuing authority.

S0d amends the S0b local document model to carry `authority`. Existing cédulas are backfilled to
`DO:JCE`. A legacy passport that predates S0d and lacks issuer data remains locally readable but is
**not federable until its authority is corrected**; S0d never guesses a country.

The global equality index stores only HMAC-SHA256 over the scoped key:

```text
identity-exchange:v1|document|{kind}|{authority}|{normalized_value}
```

No raw document value and no enumerable unsalted hash is stored globally.

Insurance membership remains tenant-local administrative identity and an optional portable fact.
It is not an independent cross-organization person-match key.

## 5. Multiple strong documents for one person

One portable person may have multiple active strong identifiers:

```text
Portable Person
  ├─ cedula   | DO:JCE | <fingerprint>
  └─ passport | DO     | <fingerprint>
```

Publishing a second document for an already-bound local Party attaches that identifier to the same
portable person. If a new document would instead join two already-distinct portable persons, the
operation fails with a conflict. S0d never performs a silent global merge.

This keeps document aliases separate from same-tenant Party duplicate resolution.

## 6. Portable fact allowlist

A patient may consent to any subset of:

- `display_name`;
- `phone` (active phone/WhatsApp facts);
- `email`;
- `insurance_member` (issuer + member/policy value).

Automatic adoption requires `display_name` consent. Never portable through S0d: reservations,
appointments, queue/service history, clinical facts, notes, diagnoses, medical records,
communication history, payments or source organization/provider identity.

## 7. Persistence and privilege boundary

S0d adds:

- `portable_person_identities` — opaque global person identity;
- `portable_person_identifiers` — `(kind, authority, keyed fingerprint)` aliases;
- `portable_person_profiles` — consented portable snapshot;
- `identity_exchange_candidates` — short-lived destination-scoped opaque references carrying the
  exact document namespace used for the match;
- `organization_person_bindings` — explicit local Party ↔ portable-person link with proof and
  consent provenance.

Global identity/profile/candidate tables are not directly readable or writable by
`request_engine_app` or `request_engine_worker`. Narrow `SECURITY DEFINER` functions are the runtime
bridge. Local bindings remain tenant-isolated with FORCE RLS and are not directly exposed to the app
role.

## 8. HTTP surface

### Publish

`POST /v1/parties/{party_id}/portable-profile`

Capability: `identity_exchange.publish`. Idempotency required.

Example:

```json
{
  "document_kind": "passport",
  "document_authority": "DO",
  "consented_fields": ["display_name", "phone", "insurance_member"],
  "proof_kind": "operator_document_witness"
}
```

The server reads that exact existing local document and the consented Party facts. Clients never
submit a replacement portable profile. Success returns only `{"published": true}`; no stable global
person id is exposed.

### Match

`POST /v1/identity-exchange/matches`

Capability: `identity_exchange.match`. Idempotency required.

```json
{
  "document_kind": "passport",
  "document_authority": "DO",
  "document_value": "SC1234567",
  "proof_kind": "operator_document_witness"
}
```

No match:

```json
{"matched": false, "candidate_ref": null}
```

Match:

```json
{"matched": true, "candidate_ref": "<opaque uuid>"}
```

No PII or source-tenant metadata accompanies the result.

### Adopt

`POST /v1/identity-exchange/adoptions`

Capability: `identity_exchange.adopt`. Idempotency required.

The operator resubmits the same scoped witnessed document, candidate and import consent. Request
Engine recomputes the fingerprint, consumes only a candidate created for the same
`kind + authority + fingerprint`, creates a normal destination Party through the Party registration
persistence path and creates the binding in the same transaction.

If the match was made using `passport | DO | SC1234567`, the destination Party receives that
passport from the destination operator's witnessed input. S0d never manufactures a cédula.

Portable insurance identifiers are returned after authorization but remain an explicit S0c write;
adoption does not bypass `parties.add_administrative_identifier`.

### Revoke

Portability revocation remains the next S0d tranche. Until a patient can revoke publication cleanly,
S0d is not complete for production portability governance.

## 9. Capabilities and bots

Operator capabilities:

- `identity_exchange.publish`;
- `identity_exchange.match`;
- `identity_exchange.adopt`.

They are excluded from the default bot grant subset. A raw integration principal cannot satisfy
`operator_document_witness`; an admitted acting-operator relay remains attributed to the verified
human and subject to the normal capability gate.

## 10. Configuration

Cross-organization equality requires `REQUEST_ENGINE_IDENTITY_EXCHANGE_KEY` or an explicit injected
key with at least 32 bytes. Without it, the rest of Request Engine starts but S0d commands fail
closed. There is no insecure default.

Key rotation is not yet transparent because fingerprints change. A future rotation contract must
support dual-key lookup/reindex before operators rotate this secret.

## 11. Duplicate semantics

- Same organization: local Party lookup wins before federated match.
- Cross organization: adoption creates a new local Party bound to the same portable person.
- Multiple strong documents may alias one portable person only through an already-proven local
  binding or the same existing scoped identifier.
- No cross-organization Party merge or history rewrite.
- Same-tenant duplicate Party resolution remains a separate explicit `parties.merge`/supersession
  workflow.

## 12. PostgreSQL proof obligations

Current-product proof must demonstrate:

1. runtime app/worker roles cannot select global identity/profile tables;
2. the global index stores keyed fingerprints, never raw identity-document values;
3. match returns only an opaque candidate before adoption;
4. raw integration/bot actors cannot assert `operator_document_witness`;
5. wrong document + valid candidate fails without consuming the valid candidate;
6. candidate consumption is bound to document kind, authority and fingerprint;
7. adoption creates a tenant-local Party using the destination-witnessed scoped document;
8. cédula adoption defaults to `DO:JCE` without changing existing caller ergonomics;
9. passport adoption requires an issuing country and preserves it locally;
10. equal passport numbers from different issuing countries do not match;
11. one portable person can gain both cédula and passport identifiers without duplicating the
    portable person;
12. an identifier that would join two portable persons fails rather than silently merging them;
13. source organization/Party ids never appear in match/adoption responses;
14. replay is stable and concurrent adoption cannot create duplicate local bindings;
15. existing bot grants imply none of the S0d capabilities.

## 13. Explicit limitations

S0d is an identity-portability mechanism, not a national patient record, fuzzy MPI search UI, EHR,
insurance eligibility service or clinical data exchange. Only document kinds with an explicit
normalization and issuing-authority policy may become match keys. Adding a new `kind` requires a
contract amendment, normalizer, issuer semantics and PostgreSQL proofs; there is no generic
"arbitrary document" escape hatch.
