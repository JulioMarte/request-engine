# P7 platform configuration, secrets and operational recovery — implementation handoff

Date: 2026-09-20  
Branch: `feature/platform-config-openbao-recovery`  
Baseline checkpoint before this handoff: `195ec7204aac75fa3699ffce7fca556e4f758e69`  
Authority: ADR 0015 + current guarantee inventory + current ownership/API/connection contracts  
Status: **repository implementation complete; production certification requires real deployment evidence**

## Current repository checkpoint — 2026-09-27

Repository-side P7 implementation and automated proof are closed for P7-A through P7-J and for the implementable/tooling portion of P7-K. The dedicated P7 gate migrates a clean PostgreSQL 18 database, runs the complete P7 proof set, exercises OpenBao 2.6.1 KV-v2 CAS/concurrent rotation/revocation against a real backend, and performs a clean-target OpenBao Raft restore smoke lifecycle. OIDC administration/readiness, appointment signing-key lifecycle, secret-free P7 observability, managed SMTP hot reload/env-free delivery, recovery-certification ingestion and clone fencing are implemented and automated.

The clean-target recovery tooling uses OpenBao Raft `snapshot restore -force` because a fresh target necessarily begins with different seal material. Bundle restore evidence is deliberately only `restore_applied_pending_verification`; final certification requires restart, unseal with the original snapshot keys and the full post-restore drill. This prevents the tooling from treating a successfully applied snapshot as a successfully recovered service.

A final fail-closed production certification gate now exists at `scripts/operations/p7_production_certification.py`. It accepts only three independently accepted artifacts: the intended production OpenBao topology acceptance, production SMTP acceptance, and a recovery certification containing measured **and operator-approved** RPO/RTO. It verifies evidence freshness, exact OpenBao topology identity, SMTP mailbox/throttling references, accepted RPO/RTO, and hashes all three evidence inputs into `request-engine/p7-production-certification/v1`. CI proves the gate semantics but intentionally cannot manufacture production evidence.

P7 is still **not production-certified** until the deployment-specific evidence exists:

1. controlled production SMTP acceptance, including operator-verified mailbox receipt and provider throttling/error behavior;
2. acceptance against the intended sealed/Raft OpenBao deployment topology;
3. retrieval of the encrypted recovery bundle from the real off-host destination;
4. a clean-environment PostgreSQL + OpenBao/Raft restore drill;
5. post-restore Request Engine reads and governed secret resolution;
6. offline Platform Owner recovery while OpenBao and SMTP are unavailable;
7. clone-fence verification on the restored environment; and
8. measured RPO/RTO within explicitly operator-approved limits.

These facts cannot honestly be implemented away or replaced by CI because they depend on the actual provider, storage destination, custody material and production topology. The repository now contains the tooling and fail-closed evidence gates needed to execute and certify them.

## Executive decision

P1-P6 are the trust root. Do not reopen them merely because P7 needs configuration.

P7 turns the private configuration/secret-store foundation into a governed self-hosted administrative product surface. PostgreSQL is authoritative for governed non-secret state; `PlatformSecretStore`/OpenBao owns reversible secret material; activation occurs only after provider validation/testing; runtime consumers resolve the ACTIVE revision and secret binding; and recovery is certified only from explicit operational evidence.

## Definition of Done

P7 is delivered only when both layers below are true:

### Repository/implementation layer

- governed ownership/capability checks exist on command/read surfaces;
- typed PostgreSQL configuration revisions and immutable audit facts exist;
- OpenBao secret lifecycle uses exact-version/CAS reconciliation and revocation;
- SMTP validation/test/activation uses certificate-verifying TLS/STARTTLS and authenticated production acceptance tooling;
- runtime hot reload has LISTEN/NOTIFY plus polling correctness backstop;
- Communications resolves ACTIVE managed configuration;
- OIDC administration/readiness and signing-key lifecycle are governed;
- readiness and secret-free observability exist;
- encrypted PostgreSQL + OpenBao backup/restore tooling exists;
- restore fails closed unless outbound fencing is enabled;
- offline Platform Owner recovery remains independent of OpenBao/SMTP;
- automated CI covers P7 contracts, real OpenBao adapter behavior, clean-target Raft restore smoke and final-certification fail-closed semantics.

### Deployment/operational evidence layer

Follow `docs/operations/p7-disaster-recovery-drill.md`, `docs/operations/p7-openbao-operational-acceptance.md`, and `docs/operations/p7-smtp-production-acceptance.md`. Produce the three accepted evidence artifacts and combine them with `scripts/operations/p7_production_certification.py`.

Do not mark P7 production-certified merely because CI is green. Do not fabricate provider receipts, off-host retrieval, unseal/recovery custody, RPO/RTO or a production topology reference. Losing all authoritative backups together with all offline recovery credentials remains irrecoverable by design; there is intentionally no master password or setup reopening.
