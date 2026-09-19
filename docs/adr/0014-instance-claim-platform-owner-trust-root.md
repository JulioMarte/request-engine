# 0014 — Instance claim and Platform Owner trust root

Status: Accepted (2026-09-18)

## Context

Request Engine is a self-hosted, native-first platform with a separate platform
control plane. The current trust root is established through
`platform_bootstrap_cli.py`: a privileged operator issues a one-time intent using
a bootstrap DSN and then consumes it to create the first platform Principal.

That ceremony is secure enough as an installation mechanism, but it has three
product and evidence costs:

1. it requires a private CLI/DSN path that the normal control-plane HTTP surface
   cannot exercise end-to-end;
2. it makes clean-install black-box evidence depend on an implementation-specific
   side channel rather than the same API a future administrative UI will use;
3. it is less natural for a self-hosted product than an explicit first-run
   instance-claim flow.

The accepted recovery, continuity and topology-serialization decisions in ADR
0013 remain valuable. This ADR changes only how the first effective platform
controller is established and how platform-owner authentication is defined.

## Decision

### 1. A Request Engine installation is an explicit Instance

A durable singleton instance identity is created independently of human users.
Its lifecycle is explicit and never inferred from `COUNT(users)=0`.

At minimum the instance has these durable states:

```text
UNCLAIMED
CLAIMED
```

An ephemeral setup session may have its own lifecycle, but it does not create an
intermediate authoritative Instance state that grants platform power.

A claimed instance never becomes unclaimed because a user, credential, binding,
Principal or grant is removed. Restore of a claimed database remains claimed.

### 2. First-run setup is an HTTP/TCP control-plane capability

A fresh `UNCLAIMED` instance exposes a narrow unauthenticated setup surface on
the **platform control plane only**. It is not mounted on the tenant/data-plane
API.

The normal interactive product journey is:

```text
UNCLAIMED instance
  -> create bounded SetupSession
  -> establish native identity material
  -> enroll at least one phishing-resistant authenticator
  -> issue one-time recovery codes
  -> finalize claim atomically
  -> Platform HUMAN Principal + active binding + platform-owner-v1
  -> CLAIMED
```

After claim, setup-creation/finalization operations fail closed permanently.

### 3. SetupSession is not a Principal

A SetupSession is short-lived installation authority scoped exclusively to
`/v1/setup/**`. It is not a HUMAN Principal, tenant member, PlatformActorContext,
delegation, API key or normal native session.

No platform capability is usable before finalization.

SetupSession material must be random, digest-only at rest, bounded by TTL,
non-refreshable and explicitly consumed/expired/revoked.

### 4. Platform Owner is a policy, not an authorization bypass

The first user is presented to humans as the **Platform Owner** but is represented
internally as a normal HUMAN platform Principal with an immutable,
versioned initial policy, beginning with `platform-owner-v1`.

There is no `is_superuser`, wildcard authorization bypass or code path in which
"owner" skips capability, revision, owner or resource checks.

Future policy expansion appends `platform-owner-v2`, etc.; existing owners do
not silently receive newly invented capabilities merely because of their label.

### 5. Platform may have multiple owners/controllers

The first owner is special only by provenance (`installation_claim`), not by a
permanent unique authorization type. Subsequent owners are created through a
governed invitation/authority flow.

The platform continuity invariant remains:

```text
after every authority/identity mutation:
at least one effective platform controller remains reachable by an accepted
authentication path
```

Operational guidance SHOULD maintain at least two independent controllers, but
the hard transactional invariant is at least one.

### 6. Owner activation requires phishing-resistant authentication

The initial owner is not effective until at least one WebAuthn credential with
user verification has been successfully registered and bound to the identity.

Passwords may remain as a supported native credential for compatibility and
fallback, but possession of a password alone is not sufficient to finalize the
initial Platform Owner.

TOTP may be supported as a secondary fallback factor. Recovery codes are
single-use recovery material, not equivalent to a phishing-resistant step-up.

The authentication model must carry method/assurance/freshness facts so sensitive
operations can require more than merely "session exists".

### 7. Instance recovery is separate from first-run claim

Loss of all owner credentials MUST NOT reopen setup.

Emergency recovery is a distinct, auditable deployment-trust ceremony and
continues to obey ADR 0013 principles: bounded authority, explicit provenance,
continuity checks, no universal force switch, no silent root creation, no secret
in ordinary logs/audit/outbox.

Recovery should restore an existing owner where possible. If emergency creation
of a replacement controller is ever supported, it requires a separate accepted
contract and immutable recovery provenance.

### 8. Three deployment claim modes are supported conceptually

The product architecture permits:

- **interactive** — self-hosted first-run wizard;
- **protected interactive** — same HTTP flow gated by deployment-provided setup
  proof for installations exposed before the owner can claim them;
- **automated** — deployment automation drives the same setup/finalize semantics
  over HTTP/TCP.

The modes must converge on the same authoritative claim command and invariants.
No mode may implement a second privileged SQL business path.

Exact environment variable names and deployment UX are implementation details
until the implementation plan is executed.

## Relationship to ADR 0013

ADR 0013 remains accepted except where this ADR narrows/supersedes its older
bootstrap assumptions.

Still authoritative:

- D1 governed recovery and distinct-human approval where required;
- D2 secret delivery through a dedicated secret store/channel;
- D3 self-linking requiring proof, never merge-by-email;
- D4 controller continuity as a post-state invariant;
- D5 identity-topology serialization and lock-order discipline;
- D6 native-first, private control plane, fail-closed configuration.

Superseded/clarified:

- the first controller no longer requires an operator-only CLI/DSN ceremony;
- "native authenticatable path" is not defined as password-credential-only;
  WebAuthn/passkey credentials are first-class accepted native paths;
- first-run bootstrap and break-glass recovery are explicitly different systems.

## Consequences

- `platform_bootstrap_cli.py` and bootstrap-intent runtime use become migration
  targets, not the future canonical installation interface.
- Existing migrations remain immutable history. Removal/retirement happens
  through new migrations and code changes, not by editing applied revisions.
- The reusable Docker system/E2E platform must eventually establish the first
  owner exclusively through real TCP against the control plane.
- WebAuthn, authentication assurance, setup sessions, Platform Owner policy and
  instance recovery become prerequisites for declaring the control plane
  production-complete.
- A future admin UI is a client of the same canonical HTTP operations; it receives
  no private bypass.

## Rejected alternatives

### Keep CLI as canonical and add UI later

Rejected because it leaves the clean-install trust root outside the canonical
HTTP/TCP product boundary and preserves two administrative execution models.

### First inserted user wins via a user-count check

Rejected because it is implicit, race-prone and can accidentally reopen after
deletion or partial restore.

### Permanent magic root / `is_superuser`

Rejected because it bypasses Request Engine's capability, provenance and
continuity model.

### Reopen setup after owner loss

Rejected because it converts account loss into an unauthenticated platform
takeover surface.

### Require SMTP or external IdP before claim

Rejected because native-only and air-gapped installations must be able to claim
the instance and then configure delivery/providers.

## References

Normative implementation details are in
`architecture/instance-claim-platform-owner-plan.md`.

Security design was checked against current NIST SP 800-63B-4 guidance,
WebAuthn Level 3, OWASP Authentication/MFA guidance, and established self-hosted
first-run patterns. These external sources guide implementation; repository
contracts remain the local normative authority.
