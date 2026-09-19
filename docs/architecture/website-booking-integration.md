# Integrating an appointment website

Request Engine is the transactional backend, not the website's conversational or
presentation runtime. Keep an INTEGRATION workload credential in your website's
server-side secret store. Never ship it in browser JavaScript, mobile bundles,
public environment variables or URLs. The website must authenticate/authorize
its own visitors before acting for a customer Party; a Party UUID is not proof
that the visitor owns that identity.

The supported HTTP shape is:

1. A tenant controller provisions an integration with `POST /v1/integrations`.
   It starts pending. Save the returned workload token immediately: idempotent
   replay deliberately does not return the secret again.
2. Assign only the needed operational capabilities with
   `PUT /v1/integrations/{id}/authority`. Desired authority is bounded by the
   controller's explicitly delegable grants, not by a supplied role name.
3. Activate with `POST /v1/integrations/{id}:activate`. Use the latest revision
   returned by `GET /v1/integrations/{id}` for each subsequent change.
4. From the website backend, authenticate using `Authorization: Bearer <token>`
   and select the tenant using `X-RE-Organization-ID`. The selected tenant is
   checked against the credential's binding; the header cannot grant access.
5. Find options with `GET /v1/appointments/slots`, supplying
   `offering_version_id`, `location_id`, `window_start` and `window_end`.
6. Book using `POST /v1/appointments`, an `Idempotency-Key`, and a body containing
   the selected `option_id` and authorized `subject_party_id`.

Booking for another Party requires the explicit `appointments.subject_override`
capability in addition to `appointments.book`; finding slots uses
`appointments.find_slots`. Customer registration/lookup additionally needs
`parties.register`/`parties.lookup`. Do not grant staff, configuration or unrelated
customer-data access just to make a booking request succeed.

Availability is advisory. A selected option does not reserve capacity; booking
revalidates authoritative state and may reject a slot that became unavailable.
On a timeout, retry the same logical booking with the **same** idempotency key
and payload. A new user booking attempt needs a new key. Never retry an ambiguous
booking blindly with a new key.

## Integration maintenance

- `GET /v1/integrations` supports bounded `limit` and cursor `after`; these queries
  require HUMAN tenant-control authority `integration.read` and never return secrets.
- `POST /v1/integrations/{id}/credentials:rotate` requires `integration.provision`,
  current revision, expiry, provenance and an idempotency key. Rotation immediately
  revokes old credentials. Coordinate the backend cutover; there is no implicit
  overlap window. If the one-time response is lost, recover by another explicitly
  authorized rotation using a new current revision/key, not secret replay.
- `POST /v1/integrations/{id}:suspend` and `:revoke` require `integration.suspend`.
  Revocation is terminal and disables workload authentication; suspension denies
  tenant execution. Reactivation requires `integration.provision`.
- Mutations record immutable provenance in the same transaction. Historical rows
  predating provenance capture are identified as incomplete, not fabricated history.

OpenAPI at `/openapi.json` is the source of truth for exact request/response/error
schemas. The integration E2E tests exercise provision, authority ceiling,
activation, appointment booking, suspension and revocation against PostgreSQL.
They do not certify your website's visitor authorization or deployment security.

## Current setup limitation

Workload authorities and initial controller provisioning still require completion
of the supported administration journey described in the identity plan. The
existing integration journey establishes those prerequisites with test fixtures;
it is not evidence of a fully self-service fresh deployment. INTEGRATION workload
governance is also distinct from the external B2B identity-provider adapter slice.
