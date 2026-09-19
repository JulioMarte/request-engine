# Authentik OIDC provider PoC (manual / opt-in)

This directory runs a self-contained [Authentik](https://goauthentik.io/) stack so a
developer can exercise the **OIDC second proof** of self-service identity linking
(`request_engine.confirm_identity_link_subject`) against a real provider.

**CI never starts this stack.** The deterministic `tests/e2e/test_identity_link_self_oidc_http.py`
proof serves its JWKS through `httpx.MockTransport` and mints tokens locally, so no
network or provider container is required for the repository gate.

## What the Request Engine OIDC verifier requires

`request_engine.platform.security.oidc_auth` is a strict resource-server profile. A
provider configuration is only usable when all of the following hold:

- **Issuer and JWKS URI are absolute HTTPS URLs** without credentials, fragment or
  query (`OidcAuthorityConfig.validate_https_endpoint`). Authentik's default
  `http://127.0.0.1:9000` issuer is therefore **not** accepted; front the server with
  a TLS-terminating proxy (Caddy/Traefik) and trust its certificate in the RE process.
- The access token is an **RFC 9068 JWT with `typ=at+jwt`** (or
  `application/at+jwt`), signed **RS256**, with `iss`, `aud`, `sub`, `exp`, `iat`,
  `client_id` and `jti` present. An OIDC **ID token** (`typ=JWT`) is rejected.
- The token **audience is the RE resource/client id** recorded in the authority's
  `configuration_ref`, not a browser-facing origin.

Authentik's stock access token header may be `typ: JWT`. Confirm the emitted header
(or the provider's token configuration) before expecting the RE verifier to accept it;
this is the single most likely reason a stock local Authentik stack fails the confirm
step.

## Bring it up

```bash
cd deploy/authentik
cat > .env <<'EOF'
AUTHENTIK_SECRET_KEY=change-me-to-50-random-characters
AUTHENTIK_POSTGRESQL__PASSWORD=change-me
AUTHENTIK_BOOTSTRAP_PASSWORD=change-me-admin-password
AUTHENTIK_BOOTSTRAP_EMAIL=admin@example.test
AUTHENTIK_TAG=2024.12.3
EOF
docker compose --env-file .env up -d
```

The four services (`server`, `worker`, `postgresql`, `redis`) share the
`request-engine-authentik` network. `server` runs migrations on first start; the
`worker` retries until they complete. The UI is at `http://127.0.0.1:9000`
(bootstrap login `akadmin` + `AUTHENTIK_BOOTSTRAP_PASSWORD`).

If the Request Engine app runs in a container, attach it to the same network
(`docker network connect request-engine-authentik <re-container>`) or publish the
provider behind the TLS proxy described above.

## Create the OAuth2 / OIDC provider and application

1. **Directory → Users**: create the federated human that will become the linked
   subject (note its `sub`/username).
2. **Applications → Create with Provider**, choose **OAuth2/OpenID Provider**:
   - Authorization flow: the default implicit/authorization flow.
   - Client type: **Confidential** (or Public for a browser PKCE flow).
   - Redirect URIs: the client you will use for the PoC.
   - Under **Advanced protocol settings**, select an RS256 signing keypair and keep
     the default scopes.
3. Name the application, e.g. `request-engine`; the slug becomes part of the issuer.
4. Read the values from the provider page:
   - **Issuer**: `https://<authentik-host>/application/o/request-engine/`
   - **JWKS URI**: `https://<authentik-host>/application/o/request-engine/jwks/`
   - **Audience**: the provider **Client ID** (Authentik sets `aud` to the client id).

## Register the authority in Request Engine

Insert one active `oidc` authority so both the login arm and the identity-link
second-proof verifier can resolve it. The reader parses `configuration_ref` as JSON
with `jwks_uri` and `audience`:

```sql
INSERT INTO request_engine.identity_authorities (
    kind, issuer_or_environment, status, configuration_ref
) VALUES (
    'oidc',
    'https://<authentik-host>/application/o/request-engine/',
    'active',
    json_build_object(
        'jwks_uri', 'https://<authentik-host>/application/o/request-engine/jwks/',
        'audience', '<client-id>'
    )::text
);
```

The Request Engine deployment must compose the OIDC arm
(`HttpSettings.oidc_enabled`) so that `identity_link_verifier` is wired; without it an
OIDC proof is rejected with `identity_link_not_configured`.

## Exercise the link

1. Create a link intent targeting the authority id:
   `POST /v1/me/identity-link-intents`
   `{"target_authority_id": "<authority-uuid>", "provenance_reference": "authentik-poc"}`.
2. Obtain an `at+jwt` access token for the federated user from Authentik.
3. Confirm:
   `POST /v1/me/identity-link-intents/{intent_id}:confirm`
   `{"proof": {"kind": "oidc", "access_token": "<token>"},
     "expected_actor_binding_revision": <revision>,
     "provenance_reference": "authentik-poc"}`.
4. Verify a second active `identity_bindings` row exists for the actor Principal with
   `subject_id` equal to the token `sub` and `identity_authority_id` equal to the
   Authentik authority.

## Tear down

```bash
docker compose --env-file .env down -v
```
