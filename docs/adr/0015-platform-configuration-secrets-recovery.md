# 0015 — Self-hosted platform configuration, secrets and break-glass recovery

Status: Accepted

## Context

Request Engine historically composes SMTP, Vault and cryptographic deployment
settings from environment variables at process startup. That is adequate for
bootstrap but not for a self-hosted administrative platform: operational
providers should eventually be changeable through the control plane, secret
values must not live in ordinary business tables, and a secret-manager outage
must not lock the Platform Owner out of Request Engine itself.

ADR 0013 requires a separate accepted break-glass path and ADR 0014 establishes
the Instance Claim / Platform Owner trust root. This ADR defines the next
boundary without weakening either decision.

## Decision

1. **Self-hosted baseline.** Every core Request Engine capability must be
   deployable without a mandatory SaaS account. SaaS providers may be optional
   adapters only.
2. **Three configuration layers.**
   - deployment/bootstrap configuration contains only what is required before the
     control plane can start;
   - non-secret operational configuration and revisions belong in PostgreSQL;
   - reversible secret values belong behind a provider-neutral
     `PlatformSecretStore`.
3. **OpenBao is the reference secret backend, not the domain abstraction.**
   Request Engine depends on `PlatformSecretStore`; `OpenBaoPlatformSecretStore`
   is the self-hosted reference implementation. HashiCorp Vault may remain a
   compatibility adapter.
4. **No secret replay for administrators.** Administrative product APIs may
   write, rotate, revoke and inspect metadata but never return stored plaintext.
   Runtime consumers may resolve plaintext only through the technical
   `PlatformSecretStore` boundary.
5. **Version-safe writes.** Secret creation is create-if-absent and rotation
   requires an exact expected backend version. Blind overwrite is not an
   accepted mutation semantic.
6. **Machine authentication.** The production reference uses OpenBao AppRole
   through OpenBao Proxy auto-auth. Request Engine does not carry a permanent
   root/static OpenBao token. Separate roles/policies must be used for control
   mutation and runtime read where deployment topology allows it.
7. **Independent human recovery.** OpenBao is not the human access trust root.
   The recovery codes returned once during Instance Claim remain digest-only in
   PostgreSQL and one unused code can atomically replace the owning native
   identity's password. This path requires neither the old password, SMTP,
   OpenBao/Vault, a current session nor a working passkey. It never reopens
   first-run setup and never reveals the old password.
8. **No master backdoor.** Losing all authoritative database state/backups and
   all offline recovery material is irrecoverable. Request Engine does not
   synthesize credentials or hide a universal recovery password.
9. **Disaster recovery is two-dimensional.** A production recovery package must
   protect both Request Engine authority state (PostgreSQL + offline recovery
   codes) and OpenBao authority state (Raft snapshots + unseal/recovery
   material). Restore/clone procedures must fence external side-effect providers
   until explicitly reactivated.
10. **Configuration APIs follow trust-root ordering.** The configuration/secret
    admin surface is not exposed until P5 establishes governed additional
    Platform Owner/admin lifecycle and the existing recent
    `PHISHING_RESISTANT` guard can protect high-risk mutations.

## Consequences

- OpenBao outages can disable operations that require a secret, but cannot by
  themselves prevent the Platform Owner from resetting a native password with an
  offline recovery code.
- PostgreSQL remains the authority for which secret ID/version/configuration is
  active; OpenBao owns only reversible secret material.
- Runtime hot reload, typed configuration revisions, SMTP/provider activation,
  notification configuration, keyrings and OIDC administration build on this
  boundary rather than environment-only composition.
- Backups and break-glass drills become part of production acceptance, not an
  operator afterthought.

## Rejected alternatives

- **Store encrypted secrets in PostgreSQL with one master key in `.env`.**
  Rejected because Request Engine would become responsible for envelope
  encryption, master-key lifecycle, rotation, revocation and compromise
  recovery.
- **Make OpenBao/Vault mandatory for Platform Owner login/recovery.** Rejected
  because failure or loss of the secret manager would become a total
  administrative lockout.
- **Permanent root token in Request Engine.** Rejected because it creates an
  unnecessary high-impact long-lived credential.
- **Generic key/value settings table.** Rejected for the eventual product
  surface; configuration is typed/versioned by capability/provider.
- **Hidden master password.** Rejected because it defeats the trust model and
  turns recovery convenience into a universal compromise path.
