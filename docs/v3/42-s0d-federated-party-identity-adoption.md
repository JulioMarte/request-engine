# S0d — Federated Party identity adoption

Status: normative design and implementation contract stacked on S0c.
Owner module: `tenancy`.

## 1. Purpose

Independent organizations must keep independent tenant-owned `Party` records, while a patient may
choose to reuse a small set of identity/contact facts they have already supplied elsewhere.
S0d therefore models **match + adoption**, never cross-organization Party merge.

A cédula is a strong equality signal. It is not authorization to read another tenant's data.

## 2. Hard privacy boundary

- `Party`, appointments, queue/service history, communications, payments and clinical facts never
  move between organizations.
- Match never returns a source organization, source Party id, name, phone, insurer or other PII.
- A destination organization creates its own local Party.
- The destination captures the cédula again from the patient; the cédula is not copied from a
  portable profile.
- Portable data is opt-in and field-scoped.
- Bot/integration principals acting without an admitted human operator cannot assert an in-person
  document witness.

## 3. First supported proof

The first production proof is `operator_document_witness`:

1. an authorized operator sees the patient's physical identity document;
2. the operator enters the cédula;
3. the patient explicitly agrees to the requested portable fields;
4. Request Engine records the effective operator, proof kind and consented fields.

Remote subject verification is intentionally unsupported until a real channel-possession or other
authentication proof exists. The API fails closed rather than pretending WhatsApp possession exists.

## 4. Identity key

The first cross-organization match key is a Dominican cédula only:

```text
namespace = document | DO:JCE | cedula
value     = normalized 11-digit cédula
```

The global equality index stores only a keyed HMAC-SHA256 fingerprint over the namespace and
normalized value. It stores no raw cédula and no unsalted cédula hash.

S0c insurance-member lookup remains available inside a tenant. Insurance membership can be an
opt-in portable fact after a cédula-backed match, but it is not an independent cross-organization
identity key in S0d v1.

## 5. Portable data allowlist

A patient may consent to any subset of:

- `display_name`;
- `phone` (active phone/WhatsApp contact facts);
- `email`;
- `insurance_member` (issuer + member/policy value).

Never portable through S0d:

- reservations, appointments or queue history;
- service-session or clinical history;
- notes, diagnoses or medical records;
- communication history;
- payments;
- source organization/provider identity.

## 6. Persistence

S0d adds privileged cross-tenant identity state:

- `portable_person_identities` — opaque global person identity;
- `portable_person_identifiers` — keyed equality fingerprint only;
- `portable_person_profiles` — consented portable snapshot;
- `identity_exchange_candidates` — short-lived opaque destination match references;
- `organization_person_bindings` — explicit local Party ↔ portable-person link with proof and
  consent provenance.

The first four tables are not directly readable/writable by `request_engine_app`. Narrow
`SECURITY DEFINER` functions are the only runtime bridge. Bindings are tenant-filtered and expose no
foreign tenant identity.

## 7. HTTP surface

### Publish

`POST /v1/parties/{party_id}/portable-profile`

Capability: `identity_exchange.publish`.
Idempotency required.

The operator chooses portable fields. Server-side code reads the Party's existing local cédula and
facts; clients do not submit a replacement profile.

### Match

`POST /v1/identity-exchange/matches`

Capability: `identity_exchange.match`.
Idempotency required.

Input includes the witnessed cédula and `proof_kind=operator_document_witness`.

No match:

```json
{"matched": false, "candidate_ref": null}
```

Match:

```json
{"matched": true, "candidate_ref": "<opaque uuid>"}
```

No PII accompanies the match.

### Adopt

`POST /v1/identity-exchange/adoptions`

Capability: `identity_exchange.adopt`.
Idempotency required.

The operator resubmits the witnessed cédula, the opaque candidate reference and the exact fields
the patient consents to import. Request Engine re-computes the fingerprint, consumes the candidate,
creates a normal tenant-owned Party through the Party registration persistence path, and creates an
organization binding in the same transaction.

The cédula stored on the destination Party comes from the destination's witnessed input. Portable
contacts/insurance facts come only from the consented snapshot.

### Revoke

`DELETE /v1/parties/{party_id}/portable-profile` is reserved for the next S0d tranche. Until that
command exists, S0d is not complete for production portability governance.

## 8. Capabilities and bots

New operator capabilities:

- `identity_exchange.publish`;
- `identity_exchange.match`;
- `identity_exchange.adopt`.

They are not part of the documented bot grant subset. A raw integration principal cannot satisfy
`operator_document_witness`; an admitted acting-operator relay is attributed to the verified human
operator and remains subject to the semantic capability gate.

## 9. Configuration

Cross-organization equality requires `REQUEST_ENGINE_IDENTITY_EXCHANGE_KEY` (or an explicit key at
composition). The key must carry at least 32 bytes. If absent, the rest of Request Engine starts but
S0d commands fail closed as unavailable. There is no insecure default key.

Key rotation is deliberately not transparent in v1 because fingerprints would change. A future
rotation contract must support dual-key lookup/reindex before operators rotate this secret.

## 10. Duplicate semantics

- Same organization: local S0b/S0c exact lookup wins before federated match.
- Cross organization: adopt creates a new local Party bound to the same portable identity.
- No cross-organization Party merge or history rewrite.
- Historical same-tenant duplicates remain a separate explicit `parties.merge`/supersession
  workflow. S0d does not silently collapse them.

## 11. Proof obligations

Current-product PostgreSQL proof must demonstrate:

1. global tables cannot be selected directly by the runtime app role;
2. publishing stores a fingerprint, not the raw cédula;
3. another tenant can receive only an opaque match reference before adoption;
4. an integration/bot actor cannot assert `operator_document_witness` on its own;
5. wrong cédula + valid candidate fails without revealing the profile;
6. expired/consumed candidates fail closed;
7. adoption creates a tenant-local Party with only consented portable fields;
8. the adopted Party gets the destination-entered cédula, not a broadcast cédula;
9. source organization/Party ids never appear in the match/adoption response;
10. replay is stable and concurrent adoption cannot create two local bindings;
11. existing bot grants imply none of the S0d capabilities.

## 12. Explicit limitations

S0d v1 is an identity portability mechanism, not a national patient record, MPI search UI, EHR,
insurance eligibility service or clinical data exchange. It intentionally prefers a smaller,
provable privacy surface over maximum automatic reuse.
