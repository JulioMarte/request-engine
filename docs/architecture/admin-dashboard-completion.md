# Administrative dashboard completion

## Scope and meaning of complete

The private console projects the current platform-control and tenant runtime APIs.
Completion means that an administrator can discover and execute their existing
administrative tasks, inspect current state where the owner exposes a read,
use returned concurrency revisions without inventing missing revisions, and
recover from denied, unavailable, stale or ambiguous results. API discovery is
not an authorization grant. Payment and dispatch product areas are not introduced
by this UI work.

This is an interface acceptance contract, not production installation acceptance.
The console has no database/provider connection and no independent business policy.
Owner operations continue to decide authority, concurrency and durable outcomes.
See [operation projection](../16-canonical-operation-and-tool-projection-pattern.md)
and [configuration readback](administrative-configuration-readback.md).

## Task matrix

| Task | Console destination | Required behavior |
| --- | --- | --- |
| First installation and sign-in | `/setup`, `/login` | Existing owner ceremony, passkey authentication, origin/CSRF protection, opaque persistent sessions and logout |
| Operational overview | `/` | Timestamped read-only snapshot, reported readiness values, incomplete data never green, no fabricated activity totals |
| Platform owners | `/resources/owners` | Owners/invitations pagination, details, revision-bound lifecycle actions and explicit denied/error states |
| Invited owner enrollment and account readiness | `/owner-invitations/enroll`, `/account/security` | Anonymous invitation redemption without a logged-in account; invitation material absent from URLs/logs; account readiness remains distinct from operator activation |
| Controller policy adoption | `/resources/controller-policy-adoptions` | List, inspect proposed policy and consent revision, apply using that exact revision/intent; no implicit grant on viewing |
| Platform identities, configuration and recovery | `/resources` | Existing native identities, provisioners, recovery cases, configuration revisions, governed secret bindings and deployment recovery workspaces |
| Organization selection | `/my-organizations` | Only memberships returned by self-discovery; platform directory never manufactures tenant access |
| People and access | `/tenants/{organization_id}/staff`, `/staff-invitations` | Real tenant context, valid parent IDs/revisions, permission preview/apply, lifecycle/history and invitation delivery/acceptance |
| Business configuration | `/tenants/{organization_id}/configuration` | 99 current owner operations grouped into organization, locations/catalog, supply, queues, channels, Requests, Discovery, agents, integrations, authority/controller policy, identity connections and capacity/recovery policies; owner reads guide supported revision-sensitive actions |
| Advanced operations | `/operations` | Complete control-plane catalog search and typed forms; it remains an escape hatch, not a substitute for missing recipient journeys |
| Diagnostics | `/diagnostics` | Redacted process counters/errors and correlation IDs, without claiming installation-wide history |

The business workspace uses the same configured `runtime_api_base_url` as the
people workspace. The canonical runtime app mounts both business and operational
configuration routes. The console neither creates a second tenant backend nor
uses platform authority as tenant authority. Explicit Party authority fields
remain owner-validated; the selected organization does not supply a Party grant.

## Tenant runtime scope and read limitations

`TENANT_CONFIGURATION_OPERATION_IDS` classifies 99 currently mounted operations,
including public read operations needed to inspect Requests definitions and current
business information. The architecture proof loads the actual native runtime OpenAPI,
checks these IDs and every operator operation, and rejects an unclassified new operator
operation. Visibility and grouping do not grant execution permission.

`TENANT_RUNTIME_EXTERNAL_DESTINATIONS` explicitly accounts for the other runtime
operator operations: 14 staff/invitation operations already have dedicated tenant
workspaces; readiness is read by the configuration overview; 27 daily-service execution
operations remain in the operational API; 20 migration-era copilot projections remain
outside this business setup interface. This work does not claim a new daily-service
client or a bespoke editor for every typed configuration schema.

Inventory lists show active and inactive Location, Offering and ServiceQueue rows.
Their links open exact detail forms, and pagination opens a form carrying the same
filters, represented Party and cursor; the user submits **Read current state**.
Offering inventory selects the latest version, then links to its exact policy read.
Location edit links preserve the returned operational revision and current profile,
including an inactive value. Request definition reads bind publication and activation
forms to their actual positive revision and current schemas. Required Party input
remains explicit when the read does not itself take a represented Party.

`business_get_info` shows organization profile, public contacts and active locations
with hours. It does not expose concurrency revisions. Location inventory supplies the
current operational revision, but contact/hour values and revisions are not a frozen
snapshot. Discovery has no current administrative configuration inventory/detail
Query for every control; existing identifiers and current revisions must come from an
owner response. Such forms remain explicit about that requirement. No missing read is
replaced by a fabricated empty collection, revision zero, or automatic grant.

## Interaction and safety

- Private invitation redemption and recovery-code issuance require JavaScript;
  submit buttons stay disabled until the fetch handler is installed, and native
  POST fallback is denied before consuming secrets. Refresh repeats the GET page
  rather than the secret-consuming POST. Invitation proof never belongs in a URL.
- Navigation works at narrow widths and without JavaScript. With JavaScript, the
  mobile drawer contains keyboard focus, closes with Escape and returns focus to
  its trigger; inactive page content is inert while the drawer is open.
- Destructive actions require confirmation. Busy forms prevent repeated clicks
  and recover after failed/time-out requests. An ambiguous command keeps its
  original idempotency intent for reconciliation.
- Every unsafe browser request requires the same-origin boundary and a valid
  session/form CSRF token. Step-up retries preserve the submitted intent and
  concurrency preconditions; a stale revision is never silently refreshed.
- Read errors and malformed success payloads do not become empty collections or
  invent revision zero. Empty child availability/exception pages do not establish
  a parent revision. Only an explicit owner contract such as an unconfigured
  channel policy may report an initial revision of zero.
- Configuration/readiness states are non-authoritative diagnostics. A successful
  HTTP response or an empty/malformed alert payload alone cannot establish health.

## Evidence and limits

Console HTTP tests execute the real ASGI routes, template renderer, session store,
origin/CSRF checks and shared executor with controlled upstream responses. They
prove request projection and UI failure handling, not PostgreSQL authorization.
Existing owner/database/current-product lanes remain the authority for those
guarantees. Node tests execute the actual browser scripts and falsify the original
navigation/loading behavior. Chromium checks inspect rendered pages at desktop
and 320-pixel widths, keyboard focus and no-JavaScript navigation using an explicitly
simulated upstream; they are UI evidence, not production provider evidence.

Catalog and Queue provide tenant-scoped Location, Offering and ServiceQueue
inventory/detail Queries. They require current capability and explicit Party
authority and report current configuration, including inactive queues. The UI
uses those reads instead of inventing lists or revisions. Typed JSON
configuration fields remain available for complex owner schemas; reachability is not a claim that every business task has
a bespoke visual editor. Production deliverability, external durability, host
network security, human alert acceptance and operational installation remain
outside this dashboard contract.

Execution results and unresolved findings belong to the implementation/PR evidence
for this branch, not to a fabricated blanket approval of earlier review candidates.

The additive `0040_tenant_controller_v7` migration preserves immutable v6 and
existing roots. The new default manifest adds only `queue.read_configuration`
for future organizations. Existing controllers need governed dual-consent
adoption; pending v6 consent keeps its original target. Opening a workspace
does not upgrade permissions or restore revoked authority.
