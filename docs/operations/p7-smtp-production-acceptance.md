# P7 controlled production SMTP acceptance

This runbook closes the production-provider evidence gap for P7-E. Regular
unit/E2E suites prove protocol behavior but do not certify the DNS, TLS,
authentication, delivery, throttling, or error behavior of the deployment's
actual SMTP provider.

## Preconditions

Use an operator-controlled destination mailbox. Keep the SMTP password outside
the command line and repository. Supply it only through the environment variable
named by `--password-env` (default:
`REQUEST_ENGINE_SMTP_ACCEPTANCE_PASSWORD`).

The provider must use authenticated SMTP with either implicit TLS or STARTTLS.
Plain SMTP is intentionally rejected by the acceptance runner.

Before declaring production acceptance, exercise the provider's documented
throttling/rate-limit or error behavior in a controlled way and retain an
operator-readable evidence reference. Separately verify that the test message
actually arrived in the operator-controlled mailbox and retain a receipt/audit
reference for that observation. SMTP `250` acceptance proves submission to the
provider, not final mailbox delivery. The acceptance command requires both
references; it does not manufacture throttling by sending a burst of mail.

## Execute

```bash
export REQUEST_ENGINE_SMTP_ACCEPTANCE_PASSWORD='<secret>'

python scripts/operations/smtp_production_acceptance.py \
  --host smtp.example.com \
  --port 587 \
  --sender noreply@example.com \
  --username smtp-user \
  --security starttls \
  --destination operator-controlled@example.com \
  --idempotency-key p7-production-acceptance-2026-09-27 \
  --throttling-evidence-reference CHANGE-1234 \
  --delivery-evidence-reference MAILBOX-CHECK-1234 \
  --output smtp-production-acceptance.json
```

The command uses the same certificate-verifying SMTP validator and provider
tester as P7. It fails unless DNS resolves, TLS/STARTTLS is used, authenticated
SMTP succeeds, provider validation is valid, the provider accepts the controlled
SMTP submission, an operator-verified mailbox receipt reference is supplied, and
the throttling/error-behavior evidence reference is present.

The resulting JSON records the SMTP submission result and the operator-provided
mailbox evidence reference; it does not infer end-to-end delivery from SMTP
submission alone. It contains no password and no destination address. Do not attach
provider credentials, SMTP passwords, OpenBao tokens, or recovery codes to the
acceptance artifact.

## Interpretation

A successful artifact is evidence only for the provider/account actually tested.
Repeat the acceptance after materially changing the endpoint, account, DNS
configuration, or network path.

An `UNKNOWN` delivery outcome is not accepted as production certification. The
normal product semantics still preserve UNKNOWN rather than blindly retrying an
ambiguous transmission.
