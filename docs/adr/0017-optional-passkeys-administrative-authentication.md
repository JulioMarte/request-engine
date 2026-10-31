# 0017 — Optional passkeys and administrative reauthentication

Status: Accepted (2026-10-14), by explicit product-owner decision. Implementation
and evidence are in progress; acceptance of the policy is not a deployment certification.

## Context

The product owner requires initial installation and administrative confirmation to
work with a password through both HTTP and the private console. Passkey enrollment
must be optional. ADR 0014's mandatory WebAuthn claim prerequisite and the exclusive
phishing-resistant administrative admission policy are deliberately replaced.

## Decision

1. Claim requires a pending native identity with a policy-compliant password and
   setup-issued recovery codes. A verified pending passkey, when present, is
   promoted in the same transaction; its absence does not block claim. Setup
   grants no Principal, identity, credential or business authority before finalize.
   Claim remains atomic, exact-intent idempotent, single-winner and permanently
   closes setup. Existing claimed installations stay claimed.
2. Administrative mutations accept a recent normal credential proof (five minutes)
   from the trusted current session. Password reauthentication uses the existing
   `POST /auth/native/sessions:reauth` operation (`nativeSessionReauthenticate`).
   It validates the owning identity's current password and refreshes only that
   exact active session. WebAuthn step-up remains an alternative.
3. A password proves SINGLE_FACTOR, never MFA or PHISHING_RESISTANT. Assurance
   continues to reflect actual ceremonies; no request field, UI state or test
   flag can manufacture stronger evidence. The phishing-resistant guard remains
   available for operations that explicitly require that property.
4. Password confirmation does not grant capabilities, bypass revision checks,
   mutate membership or silently complete recovery. Recovery-derived/restricted
   sessions remain excluded from ordinary privileged admission. Recovery completion
   is a distinct owner operation: verified WebAuthn remains supported, and a
   password alternative must verify the recovered current credential against the
   exact recovery session and epoch under locks. Completion restores normal
   identity posture but never changes a recovery-derived session into normal
   evidence; a fresh ordinary sign-in is required before administrative use.
   Remaining recovery codes are not a completion prerequisite: a user recovering
   with the last code replenishes codes after the fresh normal sign-in.
5. The console projects these same operations, keeping Origin/CSRF and opaque
   server-side sessions. Passwords, recovery material and tokens do not enter URLs,
   ordinary logs or audit artifacts. Failed confirmation does not execute the
   pending command; successful confirmation retains its exact revision and intent.

## Operation and connection gate

- Owner: platform native authentication/installation; business owners retain
  capability, relationship, continuity and transaction authority.
- Claim: existing `POST /v1/setup:finalize` (`instanceSetupFinalize`), existing operation metadata and
  SetupSession admission. No new tool projection or caller-selected ActorContext.
- Reauthentication: existing semantic session command, current bearer resolves
  the session/identity. Password is the only proof input, not an identity selector.
- Transaction: read proof context, verify password without locks, then lock and
  revalidate current identity/credential/session before refreshing freshness.
  Concurrent revocation, password replacement or recovery must reject stale proof.
- Failure: invalid proof/session gives the existing opaque authentication failure;
  stale admission requests fresh authentication; recovery remains restricted;
  authentication throttling and no-store headers continue to apply.
- Schema: append migrations after 0041; never rewrite the accepted baseline.

## Consequences

Password-only administrators can use UI and API without a physical authenticator.
This deliberately accepts greater phishing exposure than mandatory WebAuthn.
Passkeys remain recommended and fully verified when chosen. Installation ingress
containment, password policy, admission limits, authority isolation, controller
continuity and recovery provenance remain required.

## Rejected alternatives

- Skipping authentication or suppressing admission failures for audit/test users.
- Labelling password proof as phishing-resistant or synthesizing user verification.
- A separate GUI-only authorization path or automatic recovery completion.
- Reopening setup or editing immutable migration history.

## Required evidence

Real PostgreSQL 18 must prove password-only claim, optional passkey promotion,
claim replay/conflict and concurrency, active controller continuity, exact-session
password reauthentication and revocation/recovery losers. Browser evidence must
prove setup without passkey and password confirmation of the same authorized
command; API tests must independently exercise the same operations. Failed proof,
stale revision, wrong authority and recovery restrictions must retain no effects.
