# API client journeys

Status: current integration guide, not a production acceptance certificate.
Canonical policy and operation metadata remain in docs 15/16 and each owner
contract. This guide describes composition; it introduces no alternate execution
path, automatic grants or separate operation registry.

## Choose the correct API boundary

Platform control is private installation administration. Tenant runtime is
organization-scoped business operation. Deploy and secure them separately;
do not choose the control endpoint merely because the client is called admin.
Discover each boundary's actual schema from its advertised OpenAPI URL.

Authenticate first. A native identity is a login identity, not an organization
membership or an authorization grant. Creating it does not create all three.
An unclaimed installation must first complete the supported first-owner setup
ceremony, including a real human passkey, recovery and claim; see the
[trust-root contract](instance-claim-platform-owner-plan.md). Software
authenticators in tests are not production enrollment evidence. Agents do not
claim the installation or manufacture a human passkey ceremony.

## Organization and authority discovery

1. Human clients call `GET /v1/me/organizations` with the subject bearer and
   **without** `X-RE-Organization-ID`. This discovers current active memberships;
   it does not grant access to any organization. It is not agent discovery.
2. Select a returned organization and add `X-RE-Organization-ID` to tenant
   operations. A UUID in this header is context, not authority.
3. Read `GET /v1/me/authority` to inspect the actor's own Party relationships.
   An `authority_party_id` supplied to an operation must match current authority;
   it is never a client-selected bypass or an agent-manufactured trusted value.
4. Read `GET /v1/operation-catalog`. Use each operation's `openapi_pointer` and
   `openapi_url` to resolve canonical inputs, outputs and errors. Do not infer
   operation IDs from capability strings or maintain a copied policy registry.
5. Discovery is advisory: owner validation, Party/resource relationships,
   authentication freshness and concurrency can still reject invocation.

Agents authenticate with their workload identity and a trusted selected tenant.
Their current policy intersects standing grants with allowed minus denied
capabilities and the risk ceiling. Missing policy fails closed. Authority-change
operations remain denied to agents, even if listed in a human administrator's
catalog. HTTP is the canonical agent-capable surface; do not assume every HTTP
operation has an MCP tool projection.

## Incorporating a person without granting excessive rights

Use the platform-native identity provision operation only when its operator is
authorized and the person needs an administratively provisioned login. Prefer
the staff email-invitation journey when inviting a person to an organization.

Tenant staff invitations are at `/v1/staff/invitations`: create, read delivery
state, resend or revoke with their own current lifecycle/revision rules. The
recipient authenticates, previews the invitation and accepts it. Acceptance
creates membership with zero grants; it does not confer the sender's rights.
Delivery queued, SMTP accepted, invitation accepted and rights assigned are
different outcomes. Poll the supported invitation view rather than assuming
that a successful create response means delivery.

Before replacing rights, use the read-only `POST` staff authority-plan operation at
`/v1/staff/members/{membership_id}/authority:plan`. Apply via the matching authority
command using its revision requirements. The administrator can delegate only
within the current delegable ceiling, preserving authority outside that ceiling
and the last effective controller. Never silently add wildcard/default rights.

## Reconstruct configuration before changing it

Clients must work after discarding creation responses. Re-read supported owner
collections and detail before preparing a command:

- Catalog: resource-capability vocabulary and exact OfferingVersion configuration.
- Booking: resources, assignments, commercial terms, availability and exceptions.
- Communications: GET the purpose's channel policy before its PUT. Missing policy
  is explicitly `configured=false`, revision 0 and null settings, not a default.
- Requests: definitions and exact immutable versions; inbox metadata identifies
  the definition and numeric version used by each request. Read that version,
  not the latest schema, when interpreting historical demand.

See [configuration readback](administrative-configuration-readback.md) for paths,
Party scopes and pagination. Booking empty child collections intentionally do
not prove parent existence or supply a parent revision: read the authorized
resource/assignment before changing it. Money is a decimal JSON string plus
currency; parse it with decimal arithmetic, never binary floating point.
Catalog base terms and Booking contextual configure/supersede inputs accept
decimal strings or JSON integers, not fractional JSON numbers or booleans.
Send `"amount":"19.90"` (or integer `19`), not `"amount":19.90`; the latter
returns 422 because JSON binary-float parsing can lose precision before validation.
This is an explicit pre-production transport ADAPT: quote fractional prices in
existing clients. Booking's optional `null` amount retains its existing meaning.
OpenAPI inputs advertise string/integer (and null only where optional), while
responses remain exact decimal strings. Range and significant precision limits
remain 14 integer digits/six fractional digits, with no silent rounding.
AC20 design gate: Catalog owns base terms; Booking owns contextual terms. This
changes admission schemas only, retaining each existing resource/custom method,
path, stable operationId, `catalog.manage` capability, Party scope, revision and
required idempotency policy. String-based same-intent retries retain their
original fingerprint/receipt semantics; exact equivalent representations do not
introduce new normalization or a second execution path. No new tool projection
is required: future tools must use these same owner operations and lossless inputs.

Catalog base prices accept at most14 integer digits and6 significant fractional
digits; trailing zeros are allowed when the value remains exact. Invalid or
non-finite values and extreme numeric representations are rejected before the
database binding, not silently rounded. This is a deliberate API admission rule
on top of PostgreSQL's [numeric behavior](https://www.postgresql.org/docs/18/datatype-numeric.html).
Local schedule windows use weekdays0..6 and offset-free wall-clock times, with
start before end and non-inverted validity dates. Read the location revision
before replacing hours; missing and foreign locations share the owner conflict
without leaking foreign existence.

Onboarding's business-Party blocker means no active organization-kind business
Party was found. Registering that business record does not provision a tenant
root/controller or confer a Representation. Controller/authentication blockers
are separate; follow their operator guidance rather than replacing an identity.

## Retry and concurrent-change rules

For operations whose canonical metadata requires it, persist a fresh
`Idempotency-Key` for one mutation intent before sending it.
On timeout or retryable uncertain response, resend the **same key and same
body**, including exact definition version and expected revisions. Do not
generate a new key on transport retry. Same key with changed intent conflicts.
Never treat a receipt as authorization for a new mutation. Staff/native
administration and Requests definition Commands explicitly revalidate current
authority before returning receipts. Some older Catalog, Booking and
Communications Commands return their completed, actor-bound receipt before
rechecking Representation; see the [scoped authority contract](administrative-transaction-authority.md).
Their replay policy is not a universal transaction-time revocation guarantee.
Clients must still authenticate and satisfy the operation's ingress policy;
do not use a cached receipt to infer permission to read current configuration
or execute another command.
Do not apply that protocol blindly to authentication/enrollment ceremonies or
proof-bound invitation acceptance: they have their own single-use/replay
contracts and do not all accept an Idempotency-Key. Public enrollment is not
an idempotent administrative user-provision command.

On a revision conflict, read current state and decide a new intent. Do not
silently replace the revision and replay the old key. A new accepted intent gets
a new key. For Requests submission, `definition_version` is explicit so a retry
cannot drift to a newly published schema.

Queries have no idempotency key. Follow the actual continuation field until
null; pass it under the endpoint's documented query parameter and retain filters
and tenant context. Existing names differ (`next_cursor`/`cursor`/`after` and
`next_after`/`after`); do not guess that they are interchangeable. Keyset paging
is a live collection, not a snapshot across requests.

## Handle errors as structured data

Consume `error.code`, `retryable`, `resolution` and `details`, not message prose.
The composed default validation response is `ErrorEnvelope`, not FastAPI's
`HTTPValidationError`. Messages are for humans, not stable parser input.

| Resolution | Client action |
| --- | --- |
| `fix_request` | Correct the identified fields; do not loop on identical input |
| `reauthenticate` | Obtain the required current authentication evidence |
| `request_authority` | Stop and obtain legitimate authority; changing UUIDs is not a fix |
| `refresh_and_retry` | Re-read state and choose an explicit new intent when needed |
| `retry_same_request` | Preserve body/key; retry only with bounded backoff |
| `choose_alternative` | Select another supported option; do not force stale state |
| `operator_intervention` | Stop automation and investigate configuration/infrastructure |

Do not infer retryability from HTTP status alone. Foreign identifiers may be
indistinguishable from absent identifiers. No secret, bearer or invitation proof
belongs in ordinary logs, an agent transcript or durable diagnostic output.

An unexpected failure before response headers are sent returns HTTP 500
`internal_error`, `operator_intervention`, `retryable=false`, `Cache-Control:
no-store` and a server-generated `X-Correlation-ID`. The operation outcome may be
uncertain: this response does not prove rollback. Do not blindly resubmit a
mutation or a single-use ceremony. Owner-specific errors retain their contracts.
If headers were already sent, or the caller disconnected, the server cannot
replace the response with this envelope. Response sanitization does not certify
redaction of server/proxy logs; deployment logging must protect secrets separately.

HTTP 503 `password_work_capacity_exceeded` means the refused credential-processing
work was not admitted. It carries `retry_same_request`, `retryable=true` and
`Retry-After: 1`; use bounded backoff and the operation's existing proof/key rules,
not an invented idempotency key. The password-work budget is per process, not a
distributed per-client rate limit. Canceling a caller does not free capacity until
its running thread actually finishes. Threads cannot be forcibly stopped safely;
process shutdown and deployment resource limits require separate operational
acceptance. Optional verifier rehash may be skipped when busy without denying an
otherwise valid login.

## Acceptance boundary

This guide does not certify production email delivery, provider ACLs, secret
destruction, infrastructure backup/restore or exact-head CI. Those are explicit
release gates in the [API closure plan](../testing/api-production-closure-plan-2026-10-04.md).
