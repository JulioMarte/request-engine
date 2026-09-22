# P7 configuration consumer inventory

Date: 2026-09-22  
Branch: `feature/platform-config-openbao-recovery`  
Scope: P7.0 cutover inventory required by
`p7-platform-configuration-secrets-implementation-handoff.md`.

This inventory records the configuration consumers that exist in the current
repository. It is descriptive evidence for the P7 cutover set; it is not a
license to move business ownership into `platform_configuration`.

## 1. Managed SMTP / recovery delivery

### Product-managed configuration

`email.delivery` with provider `smtp` is the first P7 managed provider.

The trusted runtime path is:

```text
PostgreSQL ACTIVE revision
  -> ActivePlatformConfigurationResolver
  -> PlatformSecretStore
  -> ManagedSmtpRecoveryDeliveryChannel
```

The resolver is revision-aware, uses LISTEN/NOTIFY only as an invalidation fast
path, and polls PostgreSQL as the correctness backstop.

Current managed consumers:

- Native recovery-address verification and recovery delivery in the control
  process.
- Governed identity-recovery delivery in the reference worker.

### Bootstrap compatibility

`request_engine.bootstrap.recovery_delivery.RecoveryDeliverySettings` still
accepts deployment/bootstrap SMTP values:

```text
REQUEST_ENGINE_SMTP_HOST
REQUEST_ENGINE_SMTP_PORT
REQUEST_ENGINE_SMTP_USERNAME
REQUEST_ENGINE_SMTP_PASSWORD
REQUEST_ENGINE_SMTP_SENDER
REQUEST_ENGINE_SMTP_STARTTLS
REQUEST_ENGINE_SMTP_SSL
REQUEST_ENGINE_RECOVERY_RESET_URL
```

The intended precedence is deterministic: an ACTIVE managed SMTP revision wins;
bootstrap SMTP is only a fallback while no managed revision exists.

P7 must not silently import bootstrap credentials into OpenBao.

## 2. Platform secret store / OpenBao

`request_engine.bootstrap.platform_secrets.PlatformSecretStoreSettings` composes
the product secret-store boundary from:

```text
REQUEST_ENGINE_OPENBAO_ADDR
REQUEST_ENGINE_OPENBAO_TOKEN
REQUEST_ENGINE_OPENBAO_NAMESPACE
REQUEST_ENGINE_OPENBAO_MOUNT
REQUEST_ENGINE_PLATFORM_SECRET_PATH_PREFIX
REQUEST_ENGINE_OPENBAO_TIMEOUT_SECONDS
```

The token may be absent when the deployment supplies authentication through the
OpenBao Proxy/AppRole reference topology. Product code depends on
`PlatformSecretStore`, not OpenBao paths.

OpenBao is therefore a technical secret backend, not configuration authority.
PostgreSQL remains authoritative for ACTIVE configuration and secret-binding
metadata.

## 3. Legacy recovery proof store

Recovery proof staging has its own bounded store contract. Current deployment
composition can use OpenBao or the historical Vault-compatible backend.

Relevant bootstrap inputs are the OpenBao/Vault recovery-store address,
namespace, mount/path prefix, timeout and machine credential settings in
`RecoveryDeliverySettings`.

This store is not the general P7 platform secret store and must not become a
dependency of offline recovery codes.

## 4. Communications providers

The current generic Communications worker provider composition is still
deployment based:

```text
REQUEST_ENGINE_WEBHOOK_BASE_URL
REQUEST_ENGINE_WEBHOOK_AUTH_HEADER
```

`communications` sends a provider request containing a typed
`template_key`, `template_version` and `render_context`. The current webhook
adapter hands that semantic payload to the remote provider/orchestrator.

Important P7-G gap:

- Communications has no in-process email template renderer today.
- Therefore P7 must not invent an email body from `template_key` or serialize
  internal render context as customer-visible mail merely to claim SMTP
  integration.
- A real managed-SMTP Communications path requires a Communications-owned
  rendering contract/implementation (or another explicitly accepted rendering
  boundary) before SMTP transport can become a generic Communications provider.

The managed SMTP recovery channel does not satisfy P7-G by itself; it is a
specialized recovery delivery path.

## 5. Outbox publisher

The reference worker currently uses deployment composition for the external
outbox publisher:

```text
REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY
REQUEST_ENGINE_OUTBOX_PUBLISH_URL
```

This is a separate transport concern. P7 must not absorb its business/event
semantics. It is, however, an outbound side-effect surface that clone fencing
must inventory before P7-K can be certified.

## 6. OIDC

OIDC runtime configuration is already durable in PostgreSQL through active
`identity_authorities` rows and the narrow
`request_auth.read_oidc_authorities()` projection.

The current verifier consumes:

- issuer;
- JWKS URI;
- audience.

The verifier performs no authority creation: successful token verification still
requires the existing IdentityBinding/Principal authority path.

P7-H is therefore not an environment-variable migration. The unresolved work is
a governed administrative lifecycle that can validate and change supported OIDC
provider metadata without weakening the existing identity-authority and binding
semantics.

No current verifier flow requires a reversible OIDC client secret. Do not invent
one until a supported flow actually needs it.

## 7. Security keys and signing material

Current deployment-owned security key material includes at least:

```text
REQUEST_ENGINE_WEBAUTHN_DECOY_KEY
REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY
REQUEST_ENGINE_IDENTITY_EXCHANGE_FINGERPRINT_KEY
```

The WebAuthn decoy key is not a product signing key; it is deployment secret
material used to produce stable non-enumerating decoys.

The appointment signing key and identity-exchange fingerprint key are real
cryptographic consumers and must be reviewed before P7-I can be closed. P7-I
must define lifetime/overlap/rotation semantics for each accepted key family
rather than blindly moving raw bytes into the generic configuration JSON.

## 8. Readiness

P7 now exposes the dedicated diagnostic capability:

```text
platform.readiness.read
GET /v1/platform/readiness
```

The first projection reports only facts currently provable from PostgreSQL for
managed SMTP. Backup evidence, restore drill evidence and clone-fence state stay
`unknown` until P7-K persists or otherwise supplies accepted operational
evidence. Readiness is diagnostic and never an authorization source.

## 9. Clone-fencing side-effect set

At minimum a production clone must be unable to emit through:

- SMTP;
- Communications webhook transport;
- external outbox publishing;
- any future OIDC administrative validation that performs provider network I/O
  if the clone policy classifies that I/O as an external side effect.

Provider callbacks are inbound and do not themselves send production effects,
but any handler that schedules outbound work inherits the outbound fence.

Hostname/environment-name guessing is not an acceptable fence.

## 10. Cutover status

| Consumer | Current source | Managed P7 status | Remaining work |
| --- | --- | --- | --- |
| Recovery SMTP | bootstrap + ACTIVE `email.delivery` | managed path implemented | production provider acceptance |
| Platform secrets | OpenBao composition | implemented | production topology/restore evidence |
| Recovery proof store | OpenBao/Vault bootstrap | intentionally separate | operational recovery evidence |
| Communications webhook | deployment env | not migrated | P7-G rendering/provider boundary |
| Generic Communications email | none | not implemented | Communications renderer + managed SMTP adapter |
| OIDC verifier metadata | PostgreSQL `identity_authorities` | existing durable source, not P7-administered | P7-H governed admin lifecycle |
| WebAuthn decoy key | deployment secret | not a P7 signing key | keep deployment-managed unless policy changes |
| Appointment signing key | deployment secret | not governed | P7-I key-family rotation design |
| Identity exchange fingerprint key | deployment secret | not governed | P7-I key-family rotation design |
| External outbox publisher | deployment factory/URL | not a P7 config target yet | clone fence / explicit future ownership decision |

## 11. P7.0 conclusion

The current repository has one coherent P7 business owner:
`platform_configuration`.

The configuration cutover set is now explicit. The next implementation slices
must not treat every deployment setting as a P7 setting. In particular:

- Communications keeps communication intent/rendering/delivery semantics.
- Tenancy/identity keeps OIDC authority and IdentityBinding semantics.
- Platform security keeps cryptographic verification mechanics.
- P7 governs installation-wide operational configuration and secret metadata.
- P7-K fences outbound side effects and proves restore behavior operationally.
