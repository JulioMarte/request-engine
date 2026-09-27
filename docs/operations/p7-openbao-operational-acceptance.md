# P7 OpenBao operational acceptance

This runbook exercises the P7 secret-store CAS and revocation guarantees against
the OpenBao endpoint used by a deployment. Unit tests prove adapter logic; this
acceptance proves the actual HTTP/backend topology behaves as required.

## Preconditions

Run against the intended OpenBao/Proxy topology with a bounded policy that may
create, update, read metadata/value, and revoke only under the configured
acceptance prefix. Do not use a permanent root token.

If the endpoint requires a direct short-lived token, place it in an environment
variable and pass only the variable name through `--token-env`. When an
OpenBao Proxy injects credentials, omit `--token-env`.

## Execute

Direct token example:

```bash
export REQUEST_ENGINE_OPENBAO_ACCEPTANCE_TOKEN='<short-lived-token>'

python scripts/operations/openbao_operational_acceptance.py \
  --address https://127.0.0.1:8100 \
  --token-env REQUEST_ENGINE_OPENBAO_ACCEPTANCE_TOKEN \
  --path-prefix request-engine/acceptance \
  --topology-reference production-openbao-raft-proxy-v1 \
  --output openbao-operational-acceptance.json
```

Proxy example:

```bash
python scripts/operations/openbao_operational_acceptance.py \
  --address http://127.0.0.1:8100 \
  --path-prefix request-engine/acceptance \
  --topology-reference production-openbao-raft-proxy-v1 \
  --output openbao-operational-acceptance.json
```

The runner creates one temporary opaque secret, then launches two rotations that
both use the same observed KV-v2 CAS version. Acceptance requires exactly one
winner and one `PlatformSecretConflict`. It verifies that the winning value,
version, and opaque operation marker agree, revokes the test secret, and proves
that the revoked secret can no longer be resolved.

The evidence includes the operator-supplied topology reference plus the non-secret
endpoint/mount/prefix/auth-mode metadata used for the run. This prevents a CI
OpenBao dev-mode artifact from being confused with acceptance of the intended
sealed/Raft production topology. It contains UUIDs/versions only for the test
secret and never writes the secret value or OpenBao token to the artifact.

## Scope

This is the real-OpenBao concurrency/CAS acceptance for P7-D. It does not replace
the disaster-recovery drill. Raft snapshot restore and post-restore governed
secret resolution are certified separately by
`docs/operations/p7-disaster-recovery-drill.md`.
