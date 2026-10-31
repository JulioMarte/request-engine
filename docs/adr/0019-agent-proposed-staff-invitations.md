# 0019 — Agent-proposed, HUMAN-approved staff invitations

Status: Accepted (2026-10-19), by explicit product-owner request. Implemented by
migration `0043_staff_invitation_proposals`; evidence is listed below. Acceptance is
not a deployment certification.

## Context

The product owner requires that an AI agent connected through the API or MCP can
"add people" (employees) to a business from a text or voice request. Each business
is expected to run a "Chief of Staff" agent: an AGENT Principal with
`operating_mode = "assisted"`, sponsored by the owner, that executes what the owner
asks. This is the §12.2 mode of
`docs/architecture/principal-agent-and-provisioning-authority-model.md` (agent
acting on behalf of a human: the human is the requesting authority, the agent is
the executing actor, and both identities must survive).

Adding a person is an authority change. `staff.invite` and `staff.manage_*` are
TENANT_CONTROL, `AUTHORITY_CHANGE` and HUMAN-only. That is enforced in Python
(`agent_risk_permitted` bans AUTHORITY_CHANGE for agents regardless of grants or
ceiling; staff commands require `PrincipalKind.HUMAN`) and in PostgreSQL
(`request_engine.assert_staff_manager` requires an active HUMAN tenant member;
`replace_agent_authority` only lets agents hold operational, non-delegable grants).
None of that may be weakened. §17 of the same document names `HUMAN_APPROVAL` as
the control for such operations; until now it had no product surface, so agents
were simply denied.

## Decision

Introduce a durable tenancy-owned resource, **StaffInvitationProposal** —
"agent proposes, human approves".

1. `staff.propose_invitation` is a new OPERATIONAL-plane command capability with
   risk class `LOW_IMPACT_WRITE`. It is agent-assignable through the ordinary
   `PUT /v1/agents/{id}/authority` (non-delegable agent grant) and must also be in
   the agent's tool/risk policy. Creating a proposal records the normalized email,
   optional display name and note, the proposer Principal (agent or human) and
   provenance. It grants nothing, stages no secret, sends nothing and creates no
   invitation. Only one pending proposal may exist per organization and email, and
   a proposal is refused while an unexpired pending invitation exists for the email.
2. Approval and rejection use the existing `staff.invite` capability (TENANT_CONTROL,
   AUTHORITY_CHANGE), are HUMAN-only, require `expected_revision`, `Idempotency-Key`
   and a recent administrative authentication (`require_recent_admin_authentication`,
   ADR 0017: a password or WebAuthn proof from the current session within five
   minutes; recovery-derived sessions are refused).
3. Approval stages the invitation proof outside every lock, then in ONE transaction
   takes the ordinary invitation gate (`request_cmd.lock_staff_invitation_admin`:
   identity-topology share, tenant staff root, current HUMAN `staff.invite`), locks
   the proposal row, revalidates `pending` + revision, writes the invitation through
   the same `PostgresStaffInvitationCommands.insert_staged_invitation` path used by
   `staff_invitation_create` (same row guard, same Communications delivery intent,
   same audit) and marks the proposal `approved` with `decided_by` and `invitation_id`.
   The invitation's inviter is the approving HUMAN, so acceptance keeps revalidating
   that human's current authority. Rejection closes the proposal without effects.
4. PostgreSQL backstops: tenant RLS (ENABLE + FORCE), a status/decision consistency
   check, a partial unique index for pending email, and a row guard that asserts the
   proposer (`request_cmd.assert_staff_invitation_proposer`) on insert and the current
   HUMAN manager on every decision, and requires an approval to link the decider's own
   pending invitation for the same email.
5. Tenant controllers can delegate the new capability: immutable
   `tenant-controller-v8` = v7 + delegable operational `staff.propose_invitation`.
   New organizations select v8. Existing v1-v7 roots reach v8 only through the
   existing dual-consent adoption (ADR 0016); nothing is backfilled.
6. The Chief of Staff pattern: the owner speaks or writes to the agent, the agent
   calls `staff_invitation_propose` (tool projection of the create route, audience
   `operator`), and the owner sees "Chief of Staff proposed …" in the approvals inbox
   (`GET /v1/staff/invitation-proposals?status=pending`, which returns
   `proposed_by_display_name` from the agent profile) and approves in the console.

## Operation gate answers

```text
Business owner            tenancy
Resource                  StaffInvitationProposal; semantic :approve / :reject
HTTP                      POST/GET /v1/staff/invitation-proposals,
                          GET /v1/staff/invitation-proposals/{id},
                          POST /v1/staff/invitation-proposals/{id}:approve|:reject
operationIds              staff_invitation_proposal_create|list|get|approve|reject
Capabilities              staff.propose_invitation (create; own-proposal get),
                          staff.read (list, get), staff.invite (approve, reject)
Kind                      command (create/approve/reject), query (list/get)
Idempotency               required on create/approve/reject, scoped per decision kind
Revision                  expected_revision on approve/reject; proposals start at 1
Party/resource authority  tenant + proposer self-scope; no Party authority involved
Tool projection           create only: tool_name staff_invitation_propose, audience
                          operator. Decisions are never projected: agents cannot run them.
Failure semantics         401/403 (incl. agent_risk_denied, recent_authentication_required),
                          404 opaque, 409 staff_invitation_proposal_duplicate /
                          staff_invitation_proposal_not_pending / revision conflict,
                          422, 503 typed staging failure on approve (retry same key)
Guarantees                INV-STAFF-INVITATION-PROPOSAL-001 (new); INV-AGENT-RISK-001
                          and staff invitation guarantees unchanged
```

Connection surface: inbound HTTP (and later MCP through the same route) → trusted
ActorContext (+ agent policy resolver) → `PostgresStaffInvitationProposalCommands`
→ one `actor_transaction`; READ (precheck, no lock) / PLAN (stage proof, no lock) /
LOCK (topology share → staff root → proposal row) / VALIDATE (pending + revision)
/ WRITE (invitation + proposal + audit + idempotency) / EMIT (Communications
delivery intent in the same transaction). Concurrent loser: revision conflict (409).

## Consequences

- Agents can now take the first step of adding staff without ever holding authority
  to add staff. The owner remains the only actor that changes who works there.
- A new pending state exists; proposals do not expire automatically (a later change
  may add expiry). Human display names for HUMAN proposers are not projected (the
  staff profile table has no application-role read path); agent display names are.
- The admin console classifies the five operations under the tenant staff workspace;
  a dedicated approvals inbox page is a follow-up UI task.

## Rejected alternatives

- **Grant `staff.invite` to agents** (or lower its risk class): breaks the hard
  invariant that AUTHORITY_CHANGE is never agent-executable and that agents hold only
  operational grants; one compromised prompt could add arbitrary staff.
- **Delegation widening** (temporary delegation of `staff.invite` to an agent): agent
  delegation is an intersection bounded to operational authority; widening it would
  create the same authority-change path with a timer.
- **Auto-approval** (approve when the requesting human "said so" in a chat): the
  conversation is model input, not authenticated human consent. Only an explicit,
  recently authenticated HUMAN decision is consent.

## Required evidence

- `tests/db/test_staff_invitation_proposals.py` (real PostgreSQL 18, application LOGIN):
  inert creation, replay and duplicate conflict, tenant isolation, approval creates
  exactly one invitation through the existing path, stale revision without effects,
  rejection, deterministic concurrent approve/reject single winner, Python and SQL
  denial of agent decisions.
- `tests/e2e/test_staff_invitation_proposals_http.py`: v8 root, agent provisioned and
  authorized through the API, propose 201, agent approve/reject/direct invite 403,
  owner inbox, approve with recent authentication, replay, reject.
- `tests/unit/test_staff_invitation_proposal_http.py`: stale/missing authentication
  cannot decide; capability classification.
- `tests/db/test_initial_controller_policy.py`: immutable v8 = v7 + one capability;
  fresh roots receive v8; replay never upgrades older roots.
