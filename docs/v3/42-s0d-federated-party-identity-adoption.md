# S0d — Federated Party identity adoption

Status: normative design and implementation contract.
Owner module: `tenancy`.
This contract extends S0b/S0c and supersedes their older assumptions where explicitly stated here.
Clinical, booking and operational tenant isolation remains unchanged.

## 1. Purpose

Independent organizations keep independent tenant-owned `Party` records. S0d provides a narrow
privacy bridge for **exact strong-identifier match + consented adoption**. It is not a global Party
registry and never reparents or merges tenant-owned Parties.

`Party` keeps the V3 kinds:

```text
person
organization
```

A reservation does not require a government identifier. A Party may be created with only a display
name and optional contact points; strong identifiers can be learned later. This is necessary for
walk-in, phone, WhatsApp and ordinary front-desk intake.

## 2. Identity strength and local lookup

Identity signals are deliberately separated by strength.

### Weak locators

`phone`, `whatsapp` and `email` are tenant-local locators. They are normalized for exact lookup but
are **not unique identities**:

- one phone number may belong to several family members;
- one email may be shared by a household, office or business;
- phone numbers and addresses may later be reassigned.

Lookup therefore returns every matching active Party. Weak locators must never trigger automatic
merge, deduplication or cross-organization federation.

### Strong identifiers

The strong key is:

```text
(kind, authority, normalized_value)
```

Current allowlist:

```text
person       | cedula   | DO:JCE                         | 11 digits
person       | passport | ISO-3166 alpha-2 issuer        | 6-17 alphanumerics
organization | rnc      | DO:DGII                        | 9 digits
```

Examples:

```text
cedula   | DO:JCE | 40212345678
passport | DO     | SC1234567
passport | US     | SC1234567
rnc      | DO:DGII| 101850043
```

Equal passport numbers from different issuers are different identities. RNC is the Dominican
strong identifier for a `party_kind="organization"`; S0d does not introduce a redundant
`legal_entity` Party kind.

A Party/document mismatch is rejected before persistence and PostgreSQL independently enforces the
same invariant. `party_kind` is immutable after Party creation and is part of registration's
idempotency fingerprint.

### RNC validation boundary

Current RNC validation is intentionally limited to canonical issuer and syntactic shape: separators
are removed and the result must be exactly nine digits. This does **not** claim that the number
exists, is active at DGII, belongs to the stated business name or passed an official online
verification. Such verification is a separate external-evidence capability and must not be faked by
normalization code.

## 3. Hard privacy boundary

- Parties, appointments, reservations, queues, service history, communications, payments and
  clinical facts never move between organizations.
- Match never returns source organization, source Party id, display name, contact information,
  taxpayer name, insurer or other PII.
- The destination always creates its own local Party.
- The destination operator witnesses and submits the strong identifier again; raw source document
  values are never copied from a portable profile.
- Portable fields are opt-in and field-scoped.
- A shared phone/email is never used as a global match key.
- Knowing a cédula, passport or RNC is an equality signal, not authorization to read another
  tenant's data.

## 4. Admitted proof

The first proof is `operator_document_witness`:

1. an authorized human operator sees the relevant document/identifier evidence;
2. the operator supplies kind, authority and value;
3. the subject or authorized business representative agrees to the portable fields;
4. Request Engine records effective operator, proof kind and consent fields.

A raw integration/bot principal cannot assert this proof. Remote subject proof remains unsupported
until a real channel-possession or equivalent verification contract exists.

## 5. Keyed global equality

The global equality index stores HMAC-SHA256 over:

```text
identity-exchange:v1|document|{kind}|{authority}|{normalized_value}
```

The key is configured with `REQUEST_ENGINE_IDENTITY_EXCHANGE_KEY` or an explicitly injected secret
of at least 32 bytes. There is no insecure default. Raw identifiers and enumerable unsalted hashes
are not stored in the global index.

Key rotation is not yet transparent because fingerprints change. Dual-key lookup/reindex remains a
deferred operational requirement.

## 6. Portable Party model and aliases

One portable Party may have multiple compatible strong aliases. For a person:

```text
Portable Party(kind=person)
  ├─ cedula   | DO:JCE | <fingerprint>
  └─ passport | DO     | <fingerprint>
```

An organization currently federates through RNC. Strong identifiers may only attach to a portable
Party of the compatible Party kind. Publishing a new alias through an already-proven local binding
may extend the same portable identity. If a new identifier would join two existing portable
identities, publication fails with a conflict; S0d never silently merges them.

## 7. Portable field policy

Both Party kinds may consent to:

- `display_name`;
- `phone` (active phone/WhatsApp facts);
- `email`.

`insurance_member` is person-only. It remains a tenant-local S0c administrative identifier and is
never an independent global match key. When consented for a person, adoption returns it as a
suggestion; writing it locally still requires the normal S0c capability.

Automatic adoption requires `display_name` consent. Never portable through S0d: appointments,
reservations, queue/service history, clinical facts, notes, diagnoses, records, communication
history, payments, source organization/provider identity or authorization/representation grants.

For organizations, RNC does not imply that any particular human may act for the organization.
Representation remains a separate authority model.

## 8. Persistence and privilege boundary

S0d owns:

- `portable_party_identities` — opaque global identity plus immutable Party kind;
- `portable_party_identifiers` — `(kind, authority, keyed fingerprint)` aliases;
- `portable_party_profiles` — publisher-scoped consented snapshots keyed by portable Party and
  `publisher_organization_id`;
- `identity_exchange_candidates` — short-lived destination/principal-scoped opaque references;
- `organization_party_bindings` — local Party ↔ portable Party proof/binding.

Publisher-scoped profiles prevent one organization from overwriting another organization's
consented snapshot. Global identity/profile/candidate tables are not directly readable or writable
by `request_engine_app` or `request_engine_worker`. Runtime access is only through reviewed narrow
`SECURITY DEFINER` functions. The executable function surface is allowlisted by CI.

## 9. HTTP surface

### Local Party intake and lookup

`POST /v1/parties` accepts `party_kind` (`person` default, or `organization`) and does not require a
strong identifier.

`GET /v1/parties/lookup` supports:

```text
phone    -> exact normalized phone/WhatsApp locator, multi-match
email    -> exact normalized email locator, multi-match
document -> exact scoped strong identifier
name     -> normalized name-prefix search
```

### Publish

`POST /v1/parties/{party_id}/portable-profile`

Capability: `identity_exchange.publish`. Idempotency required.

The server reads the requested active local strong identifier and consented local facts. Clients do
not submit an arbitrary replacement portable profile. Success exposes no global identity id.

### Match

`POST /v1/identity-exchange/matches`

Capability: `identity_exchange.match`. Idempotency required.

No match:

```json
{"matched": false, "candidate_ref": null}
```

Match:

```json
{"matched": true, "candidate_ref": "<opaque uuid>"}
```

The candidate is short lived, bound to destination organization, principal, identifier namespace
and fingerprint. No source-tenant metadata accompanies it.

### Adopt

`POST /v1/identity-exchange/adoptions`

Capability: `identity_exchange.adopt`. Idempotency required.

The operator resubmits the candidate and same witnessed scoped identifier. Request Engine verifies
the candidate, creates a normal destination Party with the portable Party's immutable Party kind,
stores the destination-witnessed strong identifier and binds the local Party in one transaction.
The source raw identifier is never copied.

If an organization has already adopted that portable identity, a competing/different-alias attempt
fails with `409 identity_exchange_already_adopted` and may expose only the winning
`existing_party_id` from that same destination organization.

## 10. Concurrency and duplicate semantics

- Same-tenant strong-identifier uniqueness is enforced in PostgreSQL.
- Shared phone/email values deliberately do not serialize or deduplicate Parties.
- Cross-organization publication of the same strong identity converges on one portable Party.
- Adoption serializes on `(destination organization, portable Party)` using a transaction-scoped
  advisory lock; unrelated organizations do not block each other.
- Candidate expiry is rechecked after lock acquisition, so waiting cannot extend authorization.
- Concurrent candidates through different aliases can create at most one destination binding.
- The losing adoption transaction rolls back Party creation and returns the destination-local
  winning Party id through the typed conflict path.
- Same-tenant Party merge/supersession remains a separate explicit workflow.

## 11. Capabilities and bots

Operator capabilities are:

- `identity_exchange.publish`;
- `identity_exchange.match`;
- `identity_exchange.adopt`.

They are excluded from the default bot grant subset. An admitted acting-operator relay must still
resolve to a verified human operator with the semantic capability; an integration cannot launder
authority by declaring a human id.

## 12. PostgreSQL and application proof obligations

Current-product proof must demonstrate at least:

1. Party registration succeeds without cédula/passport/RNC;
2. shared phone and shared email lookup return all matching local Parties without merging them;
3. `organization` Parties can be created without RNC and later resolved exactly by RNC;
4. person↔cédula/passport and organization↔RNC compatibility is enforced in application and DB;
5. `party_kind` is immutable and participates in registration idempotency;
6. runtime app/worker cannot directly select global portable tables;
7. the global index stores keyed fingerprints, never raw strong identifiers;
8. match returns only opaque candidate metadata before adoption;
9. wrong identifier + valid candidate fails without consuming the valid candidate;
10. cédula defaults to `DO:JCE`; passport requires an assigned ISO issuer; RNC defaults to
    `DO:DGII`;
11. equal passport numbers from different issuers do not match;
12. one portable person may gain cédula + passport aliases without duplicating the portable Party;
13. an alias that would join distinct portable identities fails rather than merging them;
14. cross-organization RNC adoption creates a local `organization` Party and never imports
    person-only insurance identifiers;
15. publisher snapshots remain organization-scoped;
16. source organization/Party ids never appear in match/adoption responses;
17. replay is stable;
18. concurrent alias adoption produces one local Party/binding and a typed loser conflict;
19. existing bot grants imply none of the S0d capabilities;
20. the reviewed runtime EXECUTE allowlist exactly matches the granted S0d bridge functions.

## 13. Explicit limitations and deferred work

S0d is not a national patient/customer/company registry, fuzzy MPI, EHR, insurance eligibility
service, DGII verification service or authorization directory.

Deferred work includes:

- portability revocation;
- HMAC key rotation/reindex;
- remote subject proof;
- same-tenant Party merge/supersession;
- richer profile freshness/conflict policy across multiple publishers;
- verified external RNC status/name evidence;
- additional strong identifier kinds with explicit issuer and normalization contracts.

The current app-trust model also keeps the HMAC key in the application layer. PostgreSQL verifies
that a compatible scoped local document exists but cannot independently recompute an app-held HMAC.
A threat model in which the runtime application role itself is compromised would require moving the
fingerprinting secret behind a stronger DB/service boundary.
