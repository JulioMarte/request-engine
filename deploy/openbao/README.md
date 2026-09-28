# Self-hosted OpenBao reference for Request Engine

This directory is the production-oriented reference for the Request Engine
secret-store boundary. It is deliberately independent of any SaaS.

## Trust model

- PostgreSQL remains authoritative for non-secret Request Engine state.
- OpenBao stores reversible secret material.
- Request Engine talks to a local OpenBao Proxy on port 8100 without a static
  OpenBao token.
- Proxy authenticates with AppRole, renews its token and forces that token on
  proxied API calls.
- Request Engine code depends on `PlatformSecretStore`, not directly on
  OpenBao-specific business semantics.
- The offline Request Engine recovery codes issued during Instance Claim do not
  live in OpenBao and can reset the Platform Owner password even when OpenBao is
  unavailable.

## First initialization

The production server starts sealed. Initialize it deliberately:

```bash
export BAO_ADDR=https://127.0.0.1:8200
export BAO_CACERT=$PWD/tls/ca.crt
bao operator init -key-shares=5 -key-threshold=3
```

Store the five unseal key shares in separate offline locations. Do **not** put
all shares, the initial root token, Request Engine recovery codes and backups on
the same VPS.

Unseal with any threshold set:

```bash
bao operator unseal
bao operator unseal
bao operator unseal
```

After initial policy/AppRole configuration, revoke the initial root token. A
future emergency root token can be generated through the OpenBao operator
procedure using the retained unseal/recovery material; Request Engine must never
carry a permanent root token.

## KV and policies

Enable KV v2 at `secret/` and load the bounded policies:

```bash
bao secrets enable -path=secret -version=2 kv
bao policy write request-engine-runtime policies/request-engine-runtime.hcl
bao policy write request-engine-control policies/request-engine-control.hcl
bao policy write request-engine-signing-runtime policies/request-engine-signing-runtime.hcl
bao auth enable approle
```

Create separate AppRoles for runtime read and control-plane mutation. The sample
Proxy config names `request-engine-runtime`; deployments that expose mutation
through a separate control-plane process should run a second Proxy/role with the
control policy rather than giving one super-role to every Request Engine process.

Managed appointment-option signing uses a third, narrower trust boundary. The
public HTTP process must use a dedicated Proxy/AppRole carrying only
`request-engine-signing-runtime`, which can read
`request-engine/signing/*` and nothing under `platform/*` or
`identity-recovery/*`. Configure that process with the
`REQUEST_ENGINE_APPOINTMENT_SIGNING_*` settings. The private control plane may
point the same signing settings at its control Proxy, whose policy is permitted
to create/update that isolated signing prefix.

Issue SecretIDs with response wrapping and deliver the wrapping token into
`./auth/secret-id`; place the RoleID in `./auth/role-id`. Proxy consumes and
removes the SecretID file after reading it.

## Recovery package / Definition of Done

A deployment is **not recoverable** merely because OpenBao is running. Keep and
regularly test an offline recovery package containing:

1. at least one unused Request Engine Platform Owner recovery code;
2. OpenBao unseal/recovery key shares meeting the configured threshold;
3. recent PostgreSQL backup(s);
4. recent OpenBao Raft snapshot(s);
5. the TLS CA/cert material or a documented way to reissue it;
6. deployment configuration needed to recreate PostgreSQL/OpenBao endpoints;
7. a record of the OpenBao policy/AppRole bootstrap procedure.

The package must be encrypted at rest and copied off the primary host. Recovery
drills must prove both independent paths:

- **Request Engine access recovery:** with OpenBao/SMTP unavailable, consume one
  offline Request Engine recovery code to set a new Platform Owner password,
  then log in. The old password is never recovered.
- **Secret-store disaster recovery:** initialize/restore OpenBao, restore the
  Raft snapshot, recreate Proxy/AppRole credentials, then verify Request Engine
  can resolve the secret references stored in PostgreSQL.

If the operator loses the PostgreSQL state/backups **and** all offline Request
Engine recovery codes, Request Engine cannot cryptographically reconstruct the
old identity credentials. If the operator loses OpenBao storage/backups **and**
the OpenBao unseal/recovery material, OpenBao secrets cannot be reconstructed.
There is intentionally no hidden master password/backdoor.

## Network boundary

The example binds server/proxy ports to loopback for a single-host deployment.
For Docker-only networking, remove host publication and attach the containers to
a private network. Never expose the Proxy listener publicly.

TLS is mandatory between Proxy and OpenBao in this production reference. The
Proxy's local listener may use plaintext only across a trusted local/private
boundary.

## Development vs production

`deploy/reference/compose.e2e.yaml` uses OpenBao dev mode only as deterministic
CI infrastructure. Do not copy dev mode, its fixed root token or its unsealed
behavior into production.
