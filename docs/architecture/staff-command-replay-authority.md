# Current authority for staff command receipts

Status: current strengthening of Tenancy's staff command contract.

## Operation and connection gate

Existing `staff.invite`, `staff.manage_authority` and `staff.manage_membership`
Commands retain their HTTP paths, stable operationIds, fingerprints, revision
rules and required idempotency keys. No new API, tool projection, capability or
business execution path is introduced. HUMAN ActorContext must allow the command;
current PostgreSQL authority must independently still allow it. A completed
receipt is not an authorization ticket.

Authorized replay returns the original receipt even after another command has
advanced the target revision. It does not re-execute target CAS or append audit.
Withdrawn authority returns the existing forbidden failure, including when the
caller retains an older ActorContext. New commands retain owner validation and
controller-continuity checks. Profile commands already had replay revalidation
and are not changed by this correction.

## Transaction and locking

`0012_staff_replay_authority` appends one narrow SECURITY DEFINER primitive,
`request_cmd.lock_staff_command_authority(text)`, restricted to the three named
capabilities. The schema owner owns it; PUBLIC cannot execute; the application
role receives EXECUTE only, not direct table writes or a general authority helper.
It derives tenant/principal from trusted transaction context.

Python retains orchestration in one transaction: READ/PLAN input and fingerprint;
LOCK idempotency, identity-topology share gate, canonical ordered tenant staff
root, current manager principal/membership/grant; VALIDATE current authority;
either return the completed receipt or call the existing semantic owner command;
WRITE/EMIT only on the new-command path. No network I/O occurs under locks.
The ordering matches the existing staff mutation protocol. Replay and revocation
serialize: a committed withdrawal denies replay; an authorized receipt already
under those locks may complete before withdrawal, without any new mutation.

## Evolution and proof

This is additive schema evolution and an authority correction, with no backfill
or customer-data deletion. Apply migration before deploying the new application.
Older applications tolerate the added routine, but still have the receipt defect:
rolling back application code is not a security-equivalent mitigation. Downgrade
removes the routine and must not precede removal of consumers. Accepted baseline
and revisions through 0011 remain immutable.

Guarantees preserved/strengthened: INV-AUTHORITY-001, INV-TENANT-001,
INV-IDEMPOTENCY-001, INV-ATOMICITY-001 and INV-PRIVILEGE-001. PostgreSQL 18 proof
uses restricted application connections, real grants/commands/receipts, changed
target revisions, explicit lock contention and both race winners; it checks
receipt equality, forbidden outcomes and absence of extra durable effects.
Canonical lanes remain Python quality and PostgreSQL current product proof.
Actual execution results are recorded separately in the dated testing checkpoint.
