# Agent governance inspection

Status: implemented; validation checkpoint tracked separately. Owner: Tenancy.

## Operations and authority

| Operation | HTTP | Capability | Kind | Idempotency / revision |
| --- | --- | --- | --- | --- |
| `agent_list` | `GET /v1/agents` | `agent.read` | Query | no mutation key or expected revision |
| `agent_get` | `GET /v1/agents/{agent_principal_id}` | `agent.read` | Query | no mutation key or expected revision |

These are owner-backed resource reads, not agent tools. Their audience is human
tenant operators. Authenticated ActorContext supplies organization and caller;
path IDs are target selectors, never caller authority. A current active HUMAN
Principal must hold the explicit tenant-control `agent.read` grant. Neither
agent creation rights nor a model's requested tool audience grants inspection.
The DB adapter rechecks current authority even when handed an older ActorContext.

Output includes identity, display name/purpose, sponsor, operating mode, lifecycle
status, Principal active flag, separate profile/authority revisions and sorted
active standing capabilities. It never includes bearer tokens, credential
digests or other reusable secrets. Standing capabilities do not claim effective
permission for every Party/resource; risk policy, delegation, relationship and
owner-specific checks still apply to actual execution. Profile status alone is
not a credential-availability assertion.

Lists accept UUID `after` and `limit` from 1 through 100 (default 50), ordered by
Principal UUID; `next_after` is returned for a full page. This is live pagination,
not a multi-request frozen snapshot. Foreign-tenant and nonexistent detail IDs
have the same 404. Missing authentication is 401, missing/currently revoked read
authority or non-HUMAN governance is 403, malformed pagination/UUIDs are 422.
Successful reads are `Cache-Control: no-store`. Existing lifecycle/authority
mutations still require the appropriate capability and current target revision;
clients refresh after conflict rather than replaying stale writes blindly.

## Client workflow

Use the same authenticated tenant headers as other governance operations:

```http
GET /v1/agents?limit=50
Authorization: Bearer <native-session-token>
X-RE-Organization-ID: <organization-uuid>
```

Pass a returned `next_after` as `after` to continue, stopping when it is null
(a full final page can require one additional empty request). Read an agent by
its `principal_id` before editing it. Use `authority_revision` for authority
replacement and `profile_revision` for lifecycle transitions, never interchange
them. On 409, reload the agent, reconsider the desired change and send a new
intent/idempotency key only if that change is still wanted. A retry of the same
already-completed provisioning intent is not a revision refresh.

## Connection and snapshot contract

Native/OIDC/workload trust boundary -> owner HTTP DTO -> typed application read
port -> PostgreSQL adapter under the existing tenant actor transaction. One SQL
statement checks the caller and projects target profiles/grants from one MVCC
snapshot. Authorization denial cannot become an empty successful list. Every
join/subquery remains tenant-bound; existing FORCE RLS and app SELECT privileges
remain unchanged. No writes, authoritative row locks, provider calls, events or
new cross-module business dependency are introduced.

## Initial controller policy evolution

The already-applied `tenant-controller-v1` manifest is immutable. Revision 0037
appends `tenant-controller-v2`, retaining all v1 grants and adding only delegable
tenant-control `agent.read`. New native organizations select v2; their total is
34 active grants. Existing roots keep their committed policy and grant history,
including revocations; neither migration nor replay upgrades them. A governed
upgrade command for existing controller policies remains separate work.

The private factory must verify its owner-selected policy exists as well as the
selection function being callable. Apply the additive migration before deploying
the new default, using the private-service rollout discipline in
`initial-controller-policy.md`; no public runtime table privilege is added.

## Required falsification evidence

- Native controller creation -> agent provisioning -> read/list -> assignment,
  policy, activation and booking, using HTTP revisions only.
- Reads expose fresh, distinct profile/authority revisions after mutations;
  idempotent creation replays remain original snapshots, not refresh endpoints.
- Permission revocation defeats a previously valid ActorContext at the DB adapter.
- Random and foreign IDs are equally absent; lists/pagination never cross tenants.
- Non-HUMAN and missing-capability callers cannot inspect agents; responses leak
  no credential material and produce no new authoritative facts.
- Both policy manifests remain immutable and registry-conformant; populated old
  roots retain grants/revocations through physical upgrade and replay.
- Canonical PostgreSQL 18 and Python-quality evidence is recorded separately in
  `auth-implementation-status.md`; this contract is not a completion claim.
