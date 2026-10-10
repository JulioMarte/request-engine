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
  --output smtp-send-evidence.json
```

The command uses the same certificate-verifying SMTP validator and provider
tester as P7. It fails unless DNS resolves, TLS/STARTTLS is used, authenticated
SMTP succeeds, provider validation is valid, and the provider accepts the
controlled SMTP submission. The throttling/error-behavior evidence reference is
required in the send step; mailbox evidence is recorded only after receipt.

The first command generates a unique UUID send ID and corresponding `Message-ID`.
It produces `submission_accepted_pending_mailbox_verification`, never a delivery
acceptance. SMTP `250` means the provider accepted the message for processing; it
does not prove mailbox delivery. If the result is `UNKNOWN`, do not rerun or resend
automatically: inspect the mailbox and provider logs for the recorded send ID. The
command writes its ambiguous send evidence and exits non-zero. A definite failure
can be investigated before an operator deliberately starts a new send with a new
send ID. The DNS preflight uses a bounded five-second process timeout. Provider
sockets use the configured timeout, capped at 30 seconds per socket operation.
The SMTP library performs its own hostname lookup when opening each connection;
that resolver call and the combined validation/send wall time do not have a hard
overall deadline in this runner.

After an operator observes that exact `Message-ID` in the controlled mailbox,
promote the evidence in a separate step:

```bash
python scripts/operations/smtp_production_acceptance.py \
  --verify-send-evidence smtp-send-evidence.json \
  --observed-message-id '<p7-...@request-engine>' \
  --delivery-evidence-reference MAILBOX-CHECK-1234 \
  --output smtp-production-acceptance.json
```

The accepted artifact carries the same unique send ID and `Message-ID`. The
receipt reference is collected only after the send. The artifact contains no
password or destination address. Do not attach
provider credentials, SMTP passwords, OpenBao tokens, or recovery codes to the
acceptance artifact.

## Interpretation

A successful artifact is evidence only for the provider/account actually tested.
Repeat the acceptance after materially changing the endpoint, account, DNS
configuration, or network path.

An `UNKNOWN` delivery outcome is not accepted as production certification. The
normal product semantics still preserve UNKNOWN rather than blindly retrying an
ambiguous transmission. The verifier requires the exact observed `Message-ID` and
checks that it matches the recorded send ID. Its receipt reference remains an
operator assertion rather than a mailbox API result.
