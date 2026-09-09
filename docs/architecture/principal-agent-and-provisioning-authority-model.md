# Principal, agent, and provisioning authority model

Status: **normative architecture contract**.

Branch: `cohesion/system-optimization`.

This document refines the tenant identity/authentication trust-root plan with one additional product requirement that is now considered fundamental:

> Request Engine is not a system for humans that happens to expose APIs to bots. Humans, AI agents, integrations, and system workloads are all first-class security actors, while their authority is always explicit, bounded, attributable, revocable, and derived through Request Engine policy.

Where this document is more specific than older human/staff-only wording in `identity-provider-and-staff-provisioning-plan.md`, this document is the normative clarification.

---

## 1. What we are trying to build

Request Engine must be able to operate a real organization from zero with both humans and AI agents.

A deployment must be able to reach all of these states without SQL fixtures and without requiring an external identity provider:

```text
platform trust exists
    ↓
a trusted platform administrator/provisioner can create another authorized provisioner
    ↓
that provisioner can create a brand-new business tenant
    ↓
the tenant receives its first human controller/admin
    ↓
that controller can create additional human staff
    ↓
that controller can create/register AI agents
    ↓
humans and agents receive only explicitly assigned, delegable authority
    ↓
agents can execute typed Request Engine tools as themselves
    ↓
agents may also act under narrow delegated authority when a human or another authorized Principal delegates a task
    ↓
all authority can be suspended/revoked immediately
    ↓
every important action remains attributable to the real subject, actor, technical executor, authority source, and task/purpose
```

The target is not merely "support AI tools". The target is a **general execution trust model** in which autonomous software and humans can safely operate the same transactional system.

---

## 2. Core principle: Principal is the first-class security citizen

`Principal` is the canonical Request Engine security actor.

A Principal is not synonymous with employee, user account, API key, bot, or LLM.

Conceptually Request Engine must distinguish at least:

```text
HUMAN
AGENT
INTEGRATION
SYSTEM
```

Exact enum names may follow repository conventions after the schema/code audit, but the semantic distinction is normative.

### HUMAN

A person capable of authenticating and exercising RE authority.

Examples:

```text
clinic owner
receptionist
doctor
platform operator
tenant provisioner
```

A HUMAN may have staff membership in one or more tenants, but human identity and tenant membership are different facts.

### AGENT

An autonomous or semi-autonomous software actor that reasons/selects operations and invokes Request Engine tools.

Examples:

```text
clinic WhatsApp scheduling agent
voice receptionist agent
same-day recovery agent
barbershop booking agent
hardware-store quote agent
```

An AGENT is not a fake employee and must not require a human `StaffMembership` merely to obtain authority.

### INTEGRATION

A primarily deterministic external system or connector.

Examples:

```text
Chatwoot bridge
payment webhook consumer
calendar synchronization service
CRM connector
```

### SYSTEM

An internal trusted workload whose authority exists for Request Engine platform operation.

Examples:

```text
outbox worker
scheduler
internal reconciliation worker
```

Do not collapse all non-human actors into `SYSTEM` or `INTEGRATION`. AI agents have a materially different governance and delegation lifecycle and therefore must be distinguishable.

---

## 3. Authentication, identity, actor type, and authority remain separate

The identity plan's provider-neutral chain remains valid for every Principal kind:

```text
AuthenticationAuthority
        ↓
AuthenticatedSubject
        ↓
IdentityBinding
        ↓
Principal
```

The authentication mechanism may differ by subject class.

Human examples:

```text
RE Native password/passkey
OIDC
WorkOS
Clerk
Descope
```

Workload/agent examples:

```text
RE Native workload credential
OAuth client assertion
OIDC workload identity
mTLS identity
SPIFFE-like workload identity
cloud managed identity
future workload authenticator
```

The authentication mechanism never determines business authority.

Required invariant:

```text
authenticated == identity proved
```

NOT:

```text
authenticated == authorized
```

and NOT:

```text
agent authenticated == may execute every agent tool
```

---

## 4. Authority is explicit; creation only establishes provenance and a ceiling

The identity of the creator/provisioner is security-significant, but Request Engine MUST NOT automatically clone the creator's permissions into the created Principal.

This is forbidden:

```text
A can do X,Y,Z
A creates B
therefore B automatically gets X,Y,Z
```

This would make privilege propagation implicit and would make accidental or compromised provisioning extremely dangerous.

The correct rule is:

```text
creator/provisioner identity
        ↓
provisioning provenance
        +
creator's current delegable ceiling
        +
policy for the type of Principal being created
        ↓
maximum authority that MAY be assigned
        ↓
explicit authority assignment
        ↓
created Principal's actual authority
```

Normative relationship:

```text
assigned_authority(created_principal)
    ⊆
provisioner's_delegable_authority
    ∩
provisioning_policy_ceiling
```

Possession does not imply delegability:

```text
has capability X
    !=
may delegate capability X
```

Therefore an administrator may possess a capability that policy intentionally forbids them from granting onward.

---

## 5. Every provisioned Principal must have authority provenance

For every created HUMAN, AGENT, or INTEGRATION Principal, Request Engine must be able to answer:

```text
Who created it?
Under what authority?
For which organization or platform scope?
Which policy/revision constrained creation?
Which capabilities/scopes were initially assigned?
Which of those were delegable?
Who later changed them?
What is the current authority revision?
```

Conceptually preserve provenance such as:

```text
principal_id
created_by_principal_id
provisioning_intent_id or provisioning_operation_id
provisioning_policy_id/revision
authority_source
created_at
```

Do not blindly add these exact columns if equivalent immutable audit/provenance already exists. Slice 1 must first inspect existing ownership and audit structures.

The important invariant is reconstructability, not column naming.

---

## 6. Authority planes: platform, tenant control, and operations

Request Engine must explicitly distinguish three authority planes.

### 6.1 Platform provisioning authority

This is above any individual tenant.

Its purpose is to create or authorize the creation of new tenant trust roots.

Conceptual capabilities may include:

```text
platform.principal.provision
platform.tenant_provisioner.provision
organization.provision
platform.identity.recover
```

Exact names must follow the canonical capability registry and should remain narrow.

A platform provisioner does **not** automatically receive Booking, Queue, Catalog, patient, or other tenant business authority.

### 6.2 Tenant-control authority

This operates inside one Organization.

It manages that tenant's security and administrative trust root.

Conceptual capabilities:

```text
staff.read
staff.invite
staff.manage_membership
staff.manage_authority
agent.read
agent.provision
agent.manage_authority
agent.suspend
identity.bind
```

A tenant controller cannot create a new unrelated Organization unless it separately possesses platform-level `organization.provision` authority.

### 6.3 Operational authority

This governs business work:

```text
booking.*
queue.*
catalog.*
party.*
communications.*
discovery.*
recovery.*
```

Operational authority must never implicitly confer staff/agent/platform provisioning authority.

---

## 7. The higher-level administrator requirement

The product requires a trusted administrative plane capable of onboarding new organizations from zero.

The plain-language requirement is:

> A sufficiently authorized platform administrator must be able to create another human Principal and explicitly grant that Principal the limited ability to create new business tenants. That newly created Principal can then provision a new Organization and establish its first tenant controller without receiving unrelated global or tenant business powers.

Model this as a capability/delegation relationship, not a hard-coded role hierarchy.

Conceptual flow:

```text
Platform Controller A
    has:
      platform.principal.provision
      organization.provision
    may delegate:
      organization.provision
          ↓
A provisions Human Principal B
          ↓
A explicitly grants B:
      organization.provision
      subject to platform provisioning policy
          ↓
B authenticates independently
          ↓
B provisions Organization C
          ↓
Organization C + Party + first tenant Principal + first tenant-control authority
are created/reconciled atomically
```

B is not automatically a global superuser.

B receives only the platform capabilities explicitly granted to B.

If B is allowed only to create tenants, B cannot:

```text
read Clinic X bookings
change Clinic Y staff
grant itself new platform capabilities
inspect arbitrary tenant patients
modify another tenant's catalog
```

unless separate explicit authority exists.

This distinction is mandatory.

---

## 8. Avoid a magical `SUPERADMIN` role

Do not solve platform administration by adding:

```text
role = SUPERADMIN
```

and then bypassing ordinary authorization checks.

A named UI persona such as "Platform Admin" is acceptable as a versioned policy bundle, but runtime authorization must remain semantic capabilities + scope + delegability.

Example bundle:

```text
PlatformAdmin bundle revision 2
  -> platform.principal.provision
  -> platform.tenant_provisioner.provision
  -> organization.provision
  -> platform.identity.recover
```

The bundle is convenience/provisioning policy.

It is not an authorization bypass.

This makes it possible to create narrower personas such as:

```text
TenantProvisioner
  -> organization.provision only

IdentityRecoveryOperator
  -> platform.identity.recover only

PlatformSecurityAdministrator
  -> broader platform security operations
```

without introducing one omnipotent boolean.

---

## 9. Tenant controllers may create humans and agents, but only within their ceiling

Inside a tenant, a controller may create/register new staff and AI agents if explicitly authorized.

Examples:

```text
Clinic Owner Principal
    ↓
creates Receptionist Principal
    ↓
assigns receptionist authority bundle
```

and:

```text
Clinic Owner Principal
    ↓
creates Clinic Scheduling Agent Principal
    ↓
assigns booking/queue tool authority
```

The same anti-escalation rule applies:

```text
new_principal_authority
    ⊆
creator_delegable_authority
    ∩
principal_kind_policy_ceiling
```

A receptionist who may book appointments but cannot delegate booking authority must not be able to create an agent with `booking.manage_supply` merely because the receptionist can call some booking operations.

An agent also must not be able to create another Principal with authority exceeding its own delegable ceiling.

Default recommendation:

> first implementation should not allow ordinary operational AGENT Principals to provision HUMAN Principals or new high-authority AGENT Principals unless a narrowly explicit policy requires that behavior.

Do not make agent self-replication or recursive authority delegation a default capability.

---

## 10. AgentProfile: first-class governance for AI actors

`Principal(kind=AGENT)` identifies the security actor.

Agent-specific governance should live in a separate concept rather than polluting `Principal` with LLM/runtime details.

Conceptually:

```text
AgentProfile
------------
principal_id
organization_id
name/display_name
purpose
sponsor_principal_id
status
operating_mode
policy_profile_id/revision
created_at
suspended_at
revision
```

Exact schema is subject to audit.

### Sponsor

Every ordinary tenant AGENT should have an accountable sponsor/owner Principal.

The sponsor answers:

> Who is administratively responsible for why this agent exists and what policy envelope it was given?

Sponsor does not mean every action is delegated from the sponsor.

An autonomous agent may act under its own authority while still having a human sponsor.

### Runtime metadata is not authority

Do not use:

```text
model provider
model name
prompt version
runtime host
conversation platform
```

as authorization inputs merely because they identify software configuration.

They may be recorded for observability/audit, but the stable security actor is the AGENT Principal.

---

## 11. Agent identity and agent deployment/version are different

A long-lived AGENT Principal may survive many model/runtime deployments.

Example:

```text
Principal: Clinic Front Desk Agent
    |
    +-- deployment v17: model/config/tool policy revision 17
    +-- deployment v18: model/config/tool policy revision 18
```

Do not create a new business Principal every time the prompt or LLM version changes unless the security identity itself genuinely changes.

Conversely, Request Engine must be able to suspend a dangerous runtime/deployment without erasing historical attribution to the stable AGENT Principal.

Implementation may initially keep deployment/version metadata in observability rather than a full domain table, but the semantic separation should remain.

---

## 12. Three legitimate agent authority modes

Request Engine must support three semantically different modes.

### 12.1 Agent acting as itself

The agent uses its own persistent authority.

Example:

```text
Clinic Scheduling Agent
    capabilities:
      party.lookup
      catalog.read
      booking.search
      booking.create
      booking.reschedule
```

A patient asks the agent for an appointment.

The transaction is executed by the AGENT Principal under its own tenant authority.

The patient is a business subject/Party, not the security Principal being impersonated.

### 12.2 Agent acting on behalf of a human

A human requests an operation through an AI assistant.

The system must preserve both identities:

```text
subject/requesting authority = Human H
actor executing decision      = Agent A
technical workload            = Runtime R (when distinct)
```

Do not simply replace the agent with the human's ActorContext and lose the fact that an autonomous/semi-autonomous agent selected/executed the tool.

### 12.3 Agent acting under a task delegation

A Principal delegates a narrow, temporary task to an agent.

Example:

```text
Manager H
    delegates to Agent A:
      action = booking.reschedule
      scope = Dr. Perez
      date = tomorrow
      reservations = affected set
      expires = +2 hours
```

This must not become a permanent copy of H's authority.

---

## 13. DelegationGrant: temporary authority is different from standing authority

Standing capability grants and temporary delegation solve different problems.

Conceptually:

```text
CapabilityGrant
    = what Principal A normally may do

DelegationGrant
    = what Principal A may temporarily do because Principal B delegated a bounded task
```

A `DelegationGrant` or equivalent existing structure must be able to represent, when needed:

```text
organization_id
delegator_principal_id
delegate_principal_id
purpose
allowed_capabilities
resource/scope constraints
not_before
expires_at
status
revision
parent_delegation_id (if chaining is supported)
approval/provenance reference
```

Do not add a new table until existing Representation/grant semantics are audited. Reuse them if they already express this safely.

The semantic requirement is mandatory even if implementation reuses current structures.

---

## 14. Delegated agent authority is an intersection, never an authority union

For delegated execution, the safe effective authority is conceptually:

```text
EffectiveDelegatedAgentAuthority =
    AgentPolicyCeiling
    ∩ DelegationGrant
    ∩ DelegatorCurrentDelegableAuthority
    ∩ CurrentToolPolicy
    ∩ CurrentContextPolicy
```

If the agent has its own standing authority, implementation must clearly distinguish whether an operation is being attempted under standing authority or under delegated task authority. Do not silently union unrelated authority sources in a way that defeats constraints.

A delegated action must fail if:

```text
delegation expired
agent suspended
delegator revoked
required delegator capability no longer exists
scope no longer matches
tool is not permitted
approval requirement not satisfied
```

Revoking the delegator's relevant authority must invalidate dependent delegated authority immediately or force authoritative re-evaluation before execution.

---

## 15. Evolve acting-operator semantics; do not turn them into impersonation

The current `X-RE-Acting-Operator` relay is useful for trusted integrations acting under a human operator and already preserves a technical Principal.

Do not discard that capability.

However, first-class AGENT semantics must not degrade into:

```text
agent chooses any human Principal
        ↓
agent becomes that human
```

For first-class agents, Request Engine should eventually preserve an execution context capable of expressing:

```text
organization_id
subject_principal_id       -- whose authority/request is being represented, if any
actor_principal_id         -- agent or human actually selecting/executing the operation
technical_principal_id     -- workload/relay when distinct
delegation_id              -- when delegated
current authority revision
correlation_id
interaction/task id
```

Exact fields may evolve from current `ActorContext`; do not duplicate context types unnecessarily.

The invariant is that attribution and policy must not lose actor-vs-subject distinction.

---

## 16. Agent tool access is a separate least-privilege ceiling

An AGENT Principal should not automatically receive every tool that corresponds to one of its broad business capabilities.

Introduce or reuse an explicit agent/tool policy ceiling.

Conceptually:

```text
AgentPolicy
-----------
allowed_actions/tools
resource constraints
data constraints
risk ceiling
delegation requirements
approval requirements
```

Example:

```text
Clinic Front Desk Agent

allowed:
  party.lookup
  party.register
  catalog.search
  booking.find_slots
  booking.create
  booking.reschedule
  booking.cancel
  queue.check_in

forbidden:
  staff.manage_authority
  organization.provision
  platform.principal.provision
  identity.recovery
```

Prompts are not authorization policy.

The model may be instructed to avoid an action, but the server must still make the authoritative allow/deny decision.

---

## 17. Operation risk and approvals

Agent safety needs more than RBAC because an agent can execute valid operations rapidly and autonomously.

Request Engine should be able to classify high-impact operations conceptually, without necessarily introducing a giant central enum on day one.

Useful classes include:

```text
READ
LOW_IMPACT_WRITE
REVERSIBLE_WRITE
EXTERNAL_COMMITMENT
SENSITIVE_DATA
FINANCIAL
DESTRUCTIVE
AUTHORITY_CHANGE
```

Policy may then require:

```text
AUTO
REQUESTER_CONFIRMATION
HUMAN_APPROVAL
PRIVILEGED_APPROVAL
FORBIDDEN_FOR_AGENTS
```

Examples:

```text
find appointment slots        -> AUTO
book explicitly requested slot -> normally AUTO under policy
bulk cancel reservations       -> HUMAN_APPROVAL or bounded delegation
merge duplicate patients       -> HUMAN_APPROVAL
change staff authority         -> privileged policy; default agent denial
create platform provisioner    -> privileged platform policy
```

Do not force human approval for every ordinary agent operation. That would eliminate much of the product value. Use approval as a risk-sensitive control.

---

## 18. Safety budgets are separate from authorization

A Principal may be allowed to perform an operation but still need volume/time constraints.

Conceptually support policy limits such as:

```text
max mutations per minute
max reservations changed per task
max outbound messages per task
max bulk affected resources
max financial amount
max task duration
```

This protects against the agent doing something allowed **10,000 times** because of a model/runtime defect.

Authorization answers:

> May this actor do X?

Safety budget answers:

> How much X may this actor do in this context/task/window?

They are separate controls.

---

## 19. AI agents must use the same owner-backed typed execution surface

The current F6/`operational_copilot` architecture remains directionally correct.

The invariant is:

```text
external AI reasoning/runtime
        ↓
typed Request Engine tool
        ↓
server-side identity + authority + tool/risk policy
        ↓
authoritative owner command
        ↓
domain transaction
```

Do not put LLM reasoning inside Request Engine domain owners.

Do not give the LLM direct SQL access.

Do not introduce a generic unrestricted command bus.

Do not allow the LLM to inject:

```text
organization_id
principal_id
authority_party_id
capabilities
delegation identity
```

The tool arguments describe the requested business operation; the trust context comes from authenticated server-side state.

MCP may later be exposed as an adapter over this tool surface. MCP must not become the internal authorization model.

---

## 20. Business subject is not necessarily the actor

This is crucial for scheduling, healthcare, retail, and assisted workflows.

Example:

```text
customer's daughter speaks to clinic bot

conversation participant = daughter
appointment subject Party = mother
security actor = Clinic Scheduling Agent
Organization = clinic
```

Do not collapse these identities.

`Party`, `Principal`, `Representation`, and agent execution context exist precisely so Request Engine can distinguish:

```text
who is operating
who requested the work
who the business action concerns
who/what is being represented
```

An agent booking for a patient does not need to impersonate the patient Principal.

---

## 21. Provisioning hierarchy without privilege amplification

The intended provisioning graph is:

```text
Deployment bootstrap trust
        ↓
Platform Controller Principal
        ↓ explicit delegable platform authority
Tenant Provisioner Principal(s)
        ↓ bounded organization.provision authority
Organization trust root
        ↓
Tenant Controller Principal(s)
        ├─ Human staff Principals
        ├─ Agent Principals
        └─ Integration Principals
```

Every edge is an explicit authority/delegation edge.

No edge means:

```text
child inherits everything from parent
```

Instead:

```text
child assigned authority
    ⊆ parent's delegable ceiling
    ∩ policy ceiling for that provisioning action
```

This must remain true recursively.

A chain of provisioning/delegation must never amplify authority:

```text
Authority(C)
  ⊆ DelegableCeiling(B)
  ⊆ DelegableCeiling(A)
```

except where A is invoking an independently authorized platform bootstrap/recovery mechanism whose authority comes from a different explicit trust root.

---

## 22. Platform bootstrap and recovery are exceptional trust roots

There must be a way to establish the very first platform controller and recover from catastrophic lockout.

This is not ordinary tenant or agent delegation.

It belongs to deployment/bootstrap trust and must be:

```text
narrow
explicit
audited
hard to invoke accidentally
separate from normal business APIs
```

Prefer one-time or tightly controlled provisioning intents for routine tenant creation rather than using a permanently omnipotent bootstrap secret for every signup.

The existence of platform recovery does not justify weakening normal tenant-control continuity or delegation ceilings.

---

## 23. Tenant creation from zero

A Principal with explicit `organization.provision` authority must be able to create a new business tenant through a supported owner-backed surface.

Conceptually the zero-to-one transaction creates/reconciles:

```text
Organization
Organization Party
first tenant HUMAN Principal or binds an existing eligible Principal
first tenant membership/Representation
first tenant-control grants/scopes
provisioning provenance
identity binding as needed
authority revision
audit/outbox state
```

The platform provisioner does not become a tenant employee merely because it created the tenant.

Unless policy explicitly assigns tenant authority, the creator's relationship is provisioning provenance, not standing tenant business membership.

This distinction prevents a SaaS/platform administrator from automatically gaining access to every tenant's appointments, patients, customers, queues, or catalog.

---

## 24. Creating a new user who may create companies

This product requirement must be directly supported.

A platform controller should be able to:

```text
1. create/invite a new HUMAN identity
2. establish/bind its Principal
3. assign a constrained platform provisioning policy
4. optionally grant organization.provision
5. specify whether that authority is delegable further
6. activate the Principal
7. later suspend/revoke the Principal
```

Example:

```text
Julio / Platform Controller
    ↓ provisions
Sales/Onboarding User B
    ↓ assigned
organization.provision
    ↓ can create
Clinic A
Dental Office B
Barbershop C
```

User B does **not** automatically receive tenant-control authority inside A/B/C.

A tenant's first controller is established by the tenant-provisioning operation according to explicit request/policy.

Likewise, User B cannot create User C with `organization.provision` unless B's grant explicitly includes delegability of that authority.

This rule is mandatory to prevent silent propagation of platform power.

---

## 25. Agent provisioning lifecycle

A tenant controller with explicit agent-provisioning authority should be able to:

```text
create/register agent Principal
assign sponsor
assign purpose
bind workload identity/credential
assign standing authority within delegable ceiling
assign tool/risk policy
activate
rotate credentials
suspend
reactivate
revoke
inspect effective authority
inspect provenance
```

Suggested conceptual lifecycle:

```text
PENDING
ACTIVE
SUSPENDED
REVOKED
```

Agent revocation must immediately stop business authorization even if a workload token remains cryptographically valid.

Where RE controls native workload credentials/sessions, RE should also revoke/invalidate those credentials/sessions according to policy.

---

## 26. Human staff lifecycle remains separate

Humans still require staff semantics:

```text
INVITED / PENDING
ACTIVE
SUSPENDED
REVOKED
```

Do not generalize `StaffMembership` until it becomes a vague catch-all for every Principal.

A human staff member and an AI agent may both have capabilities, but they are not the same domain relationship.

The shared layer is:

```text
Principal
IdentityBinding
Capabilities
Scopes
Delegability
AuthorityRevision
Audit/Provenance
```

The lifecycle/profile layer differs by Principal kind.

---

## 27. Source-of-truth additions

The identity plan's source-of-truth matrix is extended as follows:

| Fact | Authority |
|---|---|
| Principal kind | Request Engine |
| agent existence/status | Request Engine |
| agent sponsor/purpose | Request Engine |
| agent standing authority | Request Engine |
| agent tool/risk policy | Request Engine |
| workload credential validity | configured Authentication Authority |
| identity → Agent Principal binding | Request Engine |
| task delegation | Request Engine |
| delegation ceiling | Request Engine |
| provisioner/creator provenance | Request Engine |
| platform provisioning capability | Request Engine |
| tenant-control capability | Request Engine |
| operation approval state | Request Engine or explicit approval owner |
| LLM/model/runtime metadata | observability/deployment metadata only |
| effective business authorization | Request Engine |

An LLM provider, MCP client, chat platform, external IdP, or workload identity provider must never become the canonical source of business authority.

---

## 28. Audit contract for human and agent operations

For every security-sensitive mutation, Request Engine should be able to reconstruct the following when applicable:

```text
organization
subject/requesting Principal
actor/executing Principal
technical workload Principal
Principal kind
delegation id
provisioning/authority source
capability + scope used
authority revision
tool/action
business target
approval id/status
task/interaction/correlation id
result
```

Do not store private chain-of-thought or hidden model reasoning.

Audit verifiable facts and authorization decisions:

```text
requested operation
normalized arguments
authority used
policy decision
approval
result
```

Model/runtime/version metadata may be recorded for incident analysis, but it is not authorization evidence by itself.

---

## 29. Immediate revocation and kill switch

Humans and agents must both be revocable immediately at the RE authority layer.

For agents this is particularly important because autonomous software can act much faster than a human.

Suspending an Agent Principal must invalidate or force re-resolution of stale authorization state before another protected mutation can succeed.

The authority revision/epoch mechanism from the identity trust-root plan must therefore cover:

```text
human membership authority
agent standing authority
agent status
tool/risk policy changes
delegation changes
identity binding changes
```

A global/tenant-level agent kill switch may be added if operationally useful, but it must compose with Principal-level authority rather than bypassing it.

---

## 30. Concurrency and anti-escalation invariants

The following are completion blockers:

1. A Principal cannot grant itself more authority.
2. A HUMAN cannot create a HUMAN/AGENT/INTEGRATION Principal above its delegable ceiling.
3. An AGENT cannot create a HUMAN/AGENT/INTEGRATION Principal above its delegable ceiling.
4. Possessing a capability does not imply delegability.
5. Platform provisioning authority does not imply tenant business authority.
6. Tenant-control authority does not imply platform provisioning authority.
7. Operational authority does not imply staff/agent-management authority.
8. A tenant controller cannot grant cross-tenant authority.
9. Concurrent grant/revoke/replace operations cannot produce authority outside the allowed ceiling.
10. Revoked/suspended agent authority cannot be resurrected by stale sessions, stale task delegations, webhook replay, or last-write-wins updates.
11. Recursive provisioning/delegation cannot amplify authority through a chain.
12. A platform provisioner that creates a tenant does not automatically become its standing tenant controller.
13. A creator/provisioner cannot erase the immutable provenance of how a Principal or authority grant was created.

PostgreSQL-level proof is required for invariants that can be violated by concurrent transactions.

---

## 31. Required owner-backed management surfaces

Exact names must follow repository naming conventions. The semantic operations must eventually cover:

### Platform/principal provisioning

```text
platform_principal_provision
platform_principal_suspend
platform_principal_reactivate
platform_principal_revoke
platform_principal_authority_replace
organization_provision
```

### Human staff

```text
staff_invitation_create
staff_membership_activate
staff_membership_suspend
staff_membership_reactivate
staff_membership_revoke
staff_authority_replace
```

### Agents

```text
agent_provision
agent_read
agent_list
agent_authority_read
agent_authority_replace
agent_suspend
agent_reactivate
agent_revoke
agent_workload_binding_rotate/revoke as justified
```

### Delegation

```text
delegation_create
delegation_read
delegation_revoke
```

Do not expose generic "grant anything" or "impersonate anyone" endpoints when constrained owner commands can express the intended operation safely.

---

## 32. Required E2E proofs

### E2E A — platform controller creates a tenant provisioner

```text
1. Platform Controller A authenticates.
2. A provisions Human Principal B.
3. A grants B organization.provision, within A's delegable ceiling.
4. B authenticates independently.
5. B provisions Organization O from zero.
6. O receives its first tenant controller T.
7. B cannot read O's tenant business data unless explicitly granted tenant authority.
8. B cannot grant itself additional platform authority.
9. A revokes B's organization.provision authority.
10. B can no longer create organizations immediately.
```

### E2E B — tenant controller creates a first-class AI agent

```text
1. Tenant Controller T authenticates.
2. T provisions Agent Principal A with sponsor/purpose.
3. T assigns A narrow Booking/Queue authority and allowed tool policy.
4. A authenticates through a workload identity.
5. A reads authoritative availability.
6. A books/reschedules an allowed appointment.
7. A attempts staff.manage_authority -> DENIED.
8. A attempts organization.provision -> DENIED.
9. T suspends A.
10. A's existing credential/session can no longer authorize protected business operations.
```

### E2E C — delegated AI task

```text
1. Human H has booking.reschedule and another unrelated capability.
2. Agent A has narrow standing read authority.
3. H delegates booking.reschedule for Dr. Perez / tomorrow / two hours.
4. A performs one matching reschedule -> ALLOWED.
5. A attempts the unrelated H capability -> DENIED.
6. A attempts a different doctor/date -> DENIED.
7. Delegation expires -> DENIED.
8. H loses booking.reschedule before expiry -> A immediately loses that delegated path.
```

### E2E D — no privilege amplification through provisioning chain

```text
Platform Controller A
    delegates tenant provisioning to B
B
    may create C only if B may delegate that authority
C
    cannot obtain authority outside B's delegable ceiling
```

Prove the same under concurrent create/grant/revoke races.

### E2E E — autonomous clinic agent uses business subjects correctly

```text
patient/customer P contacts Agent A
A authenticates as Agent Principal A
A resolves/registers business Party P
A books appointment FOR Party P
Audit shows:
    actor = Agent A
    business subject = Party P
A never impersonates P merely to perform the booking
```

---

## 33. Implementation sequence amendment

Before implementing the identity plan's human-only migrations, extend the Slice 1/2 audit/contracts so they support first-class workload/agent Principals.

Recommended sequence:

```text
Slice 0  exact-head/CI truth

Slice 1  audit Principal/Representation/grants/ActorContext/auth/revocation
         + determine how Principal kinds and provisioning provenance exist today

Slice 2  provider-neutral identity contracts
         + HUMAN/AGENT/INTEGRATION/SYSTEM semantics
         + human and workload authentication subject classes
         + authority provenance/delegable ceiling contracts

Slice 3  RE Native human authentication

Slice 4  RE Native workload/agent authentication

Slice 5  platform controller + tenant-provisioner lifecycle
         + tenant creation from zero

Slice 6  tenant human staff lifecycle

Slice 7  first-class AgentProfile/lifecycle
         + standing authority
         + tool policy
         + kill/revocation proof

Slice 8  delegated task authority
         + actor/subject attribution

Slice 9  provider conformance / OIDC

Slice 10 external B2B providers

Slice 11 optional MCP projection over typed tools

Slice 12 adversarial closure
```

Do not make MCP or an LLM SDK a prerequisite for the security model. Agent identity/authority must be valid even when the caller uses ordinary typed HTTP tools.

---

## 34. Definition of Done amendment

The overall identity/trust-root work is not complete until all of the following are true in addition to the providerless/external-provider requirements already documented:

1. `AGENT` is a first-class Principal semantic, not an alias for employee or generic system account.
2. HUMAN, AGENT, INTEGRATION, and SYSTEM actors use the same canonical Principal/authority infrastructure without being forced into the same lifecycle model.
3. The creator/provisioner of a Principal is auditable.
4. Creation does not automatically clone creator authority.
5. Assigned authority is bounded by creator/provisioner delegable ceiling and policy ceiling.
6. A platform controller can create another human provisioner who can create a new Organization from zero.
7. That tenant provisioner does not automatically gain standing business authority inside tenants it creates.
8. Tenant controllers can create/register AI agents with explicit sponsor, purpose, authority, and policy.
9. AI agents can authenticate using workload credentials without pretending to be humans.
10. Agents can execute supported typed tools under their own standing authority.
11. Agents can be given narrowly bounded temporary delegated authority.
12. Delegated execution preserves subject, actor, and technical-executor attribution where applicable.
13. Delegated authority is an intersection of current ceilings/constraints, not a privilege union.
14. Agents cannot self-escalate or recursively provision more powerful actors.
15. Agent suspension/revocation immediately removes effective RE authorization.
16. Tool/risk policy is enforced server-side; prompt text is never the authorization boundary.
17. High-impact operations can require explicit approval or be forbidden for agents without affecting low-risk autonomous operations.
18. Safety budgets can constrain repeated/bulk agent actions independently of capability authorization.
19. Business Party/subject identity is not confused with the security actor executing the operation.
20. Audit/provenance can reconstruct who requested, who/what acted, under whose authority, against which target, and with what result without storing private model reasoning.
21. Platform, tenant-control, and operational authority remain separate planes.
22. No provisioning/delegation chain can amplify authority, including under concurrency.
23. Exact-head PostgreSQL proofs cover the critical provisioning, delegation, revocation, tenant-isolation, and concurrency invariants.

---

## 35. Plain-language product contract

The desired Request Engine behavior can be summarized without architecture jargon:

> Request Engine must know exactly who or what is doing work. A human employee, an AI receptionist, an integration, and an internal worker are all real actors with their own identities. Nobody gets power merely because they logged in, because an external provider called them an admin, or because a more powerful user created them.
>
> A creator may only give a new actor authority that the creator is explicitly allowed to delegate. The granted authority is written down, scoped, auditable, revisioned, and revocable.
>
> At the platform level, a trusted administrator can create other authorized onboarding users. Those onboarding users can be permitted to create a brand-new company from zero, but they do not automatically gain access to that company's patients, bookings, customers, catalog, or staff.
>
> Inside a company, its controllers can create human staff and AI agents. An AI agent is not a fake employee: it is a first-class Principal with its own workload identity, purpose, sponsor, permissions, tool limits, and lifecycle. It may work autonomously within its own standing authority or receive a narrow temporary delegation for a specific task.
>
> Request Engine, not the LLM, prompt, MCP client, identity provider, or chat platform, decides whether an operation is permitted. Every important mutation must remain attributable and must fail closed when identity, tenant, delegation, scope, revision, or approval is ambiguous or invalid.

That is the trust model the implementation must preserve.

---

## 36. Implementation status (current branch)

Status on `cohesion/system-optimization` as of migrations `0023_workload_authentication` and `0024_agent_governance` (both applied). This section is descriptive status, not a normative amendment of the contract above.

```text
Slice 1   complete
Slice 2   complete
Slice 3   complete
Slice 4   complete for RE-native workload credentials
Slice 5   complete
Slice 6   complete
Slice 7   partially complete
Slice 8   open
Slice 9   open
Slice 10  open
Slice 11  open
Slice 12  open
```

Implemented on the current branch:

- Workload bearer authentication (Slice 4, RE-native scope): `request_engine.workload_identities` / `request_engine.workload_credentials` behind the SECURITY DEFINER read boundary `request_auth.read_workload_credential`; `WorkloadCredentialAuthenticator` (`platform/security/workload_auth.py`) emits a provider-neutral WORKLOAD `AuthenticatedSubject`; `DispatchedBearerSubjectResolver` (`platform/security/workload_http.py`) deterministically dispatches one bearer-token namespace between native human sessions and workload credentials. Subject-class gating (`identity_resolution.py` `_assert_subject_class`) prevents HUMAN credentials from activating workload Principals and workload credentials from activating HUMAN Principals.
- Agent governance (Slice 7, core): `request_engine.agent_profiles` with status `pending/active/suspended/revoked`, operating mode `autonomous/assisted`, sponsor, provenance `agent_provisioning`, tenant-isolated RLS and org-bound composite FKs to `principals(organization_id, id)`; SECURITY DEFINER `request_engine.provision_agent` / `replace_agent_authority` / `transition_agent_profile` granted to `request_engine_app`. PostgreSQL enforces: agent standing authority only from the provisioner's active + delegable grants restricted to `authority_plane='operational'` (no platform/tenant-control/identity authority for AGENT Principals); agent grants always `delegable=false`; the `pending→active|revoked`, `active→suspended|revoked`, `suspended→active|revoked` state machine with `revision+1`; sponsor must be an active tenant HUMAN; self-provisioning forbidden.
- Kill switch behavior: suspension deactivates the Principal and suspends its identity binding so authorization fails closed immediately; revocation additionally revokes active workload credentials and disables the workload identity, so the bearer token stops authenticating.
- HTTP surface: `POST /v1/agents` (`agent.provision`), `PUT /v1/agents/{id}/authority` (`agent.manage_authority`), `PUT /v1/agents/{id}/status` (`agent.suspend`) in `modules/tenancy/api/agent_governance_routes.py`, HUMAN-actor gated and idempotent via `request_cmd` idempotency primitives; the one-time workload token is returned exactly once on provisioning and replay returns durable facts with `token=null`.

Proof ownership: `tests/db/test_agent_governance.py` (six real-PostgreSQL proofs), `tests/db/test_workload_authentication.py`, `tests/e2e/test_native_agent_lifecycle.py` (E2E B analog), `tests/e2e/test_platform_provisioning_journey.py` (bootstrap via the `platform_bootstrap_cli` env-driven path: tenant provisioner → organization from zero → staff lifecycle → agent lifecycle, including no-amplification and provisioner-cannot-access-tenant negatives), and unit evidence in `tests/unit/test_agent_governance_*.py`, `tests/unit/test_workload_auth.py` and `tests/unit/test_authority_plane_registry.py`.

Still open in Slice 7: tool policy, risk policy/approvals and safety budgets (sections 16-18). Slice 8 (delegated task authority with actor/subject attribution, sections 13-15) and Slices 9-12 (provider conformance, external B2B providers, optional MCP projection, adversarial closure) are open.