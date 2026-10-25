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
| First installation and sign-in | `/setup`, `/login` | Password and recovery-code claim, optional verified passkey, password or passkey sign-in, origin/CSRF protection, opaque persistent sessions and logout |
| Operational overview | `/` | Timestamped read-only snapshot, reported readiness values, incomplete data never green, no fabricated activity totals |
| Platform owners | `/resources/owners` | Owners/invitations pagination, details, revision-bound lifecycle actions and explicit denied/error states |
| Invited owner enrollment and account readiness | `/owner-invitations/enroll`, `/account/security` | Anonymous invitation redemption without a logged-in account; invitation material absent from URLs/logs; account readiness remains distinct from operator activation |
| Controller policy adoption | `/resources/controller-policy-adoptions` | List, inspect proposed policy and consent revision, apply using that exact revision/intent; no implicit grant on viewing |
| Platform identities, configuration and recovery | `/resources` | Native identities, provisioners, recovery cases, configuration revisions, governed secret bindings and deployment recovery; initial recovery binding setup at `/resources/deployment-recovery/new` |
| Organization selection | `/my-organizations` | Only memberships returned by self-discovery; platform directory never manufactures tenant access |
| People and access | `/tenants/{organization_id}/staff`, `/staff-invitations` | Real tenant context, valid parent IDs/revisions, permission preview/apply, lifecycle/history and invitation delivery/acceptance |
| Clinic setup (owners) | `/tenants/{organization_id}/setup` | Plain-language guided steps: clinic profile/contacts, location with address and weekly opening hours, services with length and price, doctors/rooms with services and weekly availability, optional walk-in line, then owner readiness and a live preview of the first free times; the business Party comes from the owner self-authority read; resumable without duplicates; owner refusals (for example a missing profile or queue permission) are explained and optional steps can be skipped |
| Business configuration | `/tenants/{organization_id}/configuration` | 99 current owner operations grouped into organization, locations/catalog, supply, queues, channels, Requests, Discovery, agents, integrations, authority/controller policy, identity connections and capacity/recovery policies; owner reads guide supported revision-sensitive actions |
| Advanced operations | `/operations` | Complete control-plane catalog search and typed forms; it remains an escape hatch, not a substitute for missing recipient journeys |
| Business home | `/tenants/{organization_id}` | Setup progress, team counts, chief of staff status and pending agent suggestions from owner reads; unavailable reads are shown as unavailable |
| Today (employees and administrators) | `/tenants/{organization_id}/today` | Live queues with call next, call now (with reason), set aside/back in line, no-show, skip, start service (choosing the doctor or room at that location) and finish service; the day's appointments in business time with check-in, attendance answer, late arrival time, move and cancel; a New visit journey that finds or registers the customer, then books a free time or adds them to a queue; denied reads are explained, never shown as empty |
| Agents and API access | `/tenants/{organization_id}/agents` | Chief of staff template and custom agents through the owner provision/activate/authority/policy sequence; one-time key reveal; MCP/HTTP connection instructions; key rotation, pause and revoke |
| Approvals | `/tenants/{organization_id}/approvals` | Agent-proposed staff invitations approved or rejected by a person with the exact proposal revision (ADR 0019) |
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
operator operations: the staff/invitation operations (including staff Representation
delegation, `staff_representations_list` and `staff_manage_representations`) belong to
the tenant staff workspace (the console does not yet render a Representation editor;
apps call the owner operations directly); readiness is read by the configuration overview; 11 daily-service operations
(day board, live queue, check-in, call next, call now, set aside, back in line, no-show,
skip, start service, finish service) are projected by the Today workspace; the remaining 16
daily-service execution operations (service pause/resume/read, staff history,
workload classification, resource activity and operational recovery) stay in the
operational API; 20 migration-era copilot projections remain outside this business setup
interface. Today is a front-desk view, not a complete daily-service client, and there is
no bespoke editor for every typed configuration schema.

Start service (`service_session_start`) needs a resource with an active assignment at
the queue's location. Today uses Delivery's `front_desk_serving_resources`
(`GET /v1/locations/{location_id}/serving-resources`), authorized by the same
`service_session.start` capability. Receptionists need no supply-configuration
capability or `operations.manage_supply` representation to choose a Resource.
The read is advisory; service start independently revalidates the assignment and
execution preconditions. The architecture proof rejects configuration commands in
`TODAY_OPERATION_IDS`. A denied read is explained rather than shown as an empty list.
Arrival on the day
board counts the owner facts: the reservation's attendance check-in, the active queue
entry created by queue check-in, and the served visit the day board keeps after
completion (`served_at` from the completed ServiceSession, `visit_arrived_at` from the
visit's queue entries). A served booking reads "Seen at HH:MM" in business time, counts
as checked in and seen, and is offered no check-in, attendance or arrival-estimate
action. Cancellation and rescheduling also refuse served visits with
`409 reservation_already_served`; the UI must not offer them as valid actions
(INV-SERVED-VISIT-001).

Today also projects public owner operations for the receptionist journey:
`parties_lookup`, `parties_register`, `catalog_search_offerings`,
`appointments_find_slots`, `appointments_book`, `appointments_reschedule`,
`appointments_cancel`, `appointments_confirm_attendance` and
`appointments_record_arrival_estimate`. Their capability exposure stays `public`
(customers and agents use the same operations for themselves) and their tool
audience stays as declared by the owner; no exposure, audience or capability metadata
was changed to place them in the console. A receptionist acts for a customer only
through the owner's own rule: delegated Party scope for that subject, or the owner's
`appointments.subject_override` capability. The console passes the subject Party and
signed slot option returned by owner reads and never decides that authority.
`TODAY_OPERATION_IDS` lists every operation Today executes; the architecture proof
checks it against the real runtime OpenAPI and the `tenant-today` destination.

Inventory lists show active and inactive Location, Offering and ServiceQueue rows.
Their links open exact detail forms, and pagination opens a form carrying the same
filters, represented Party and cursor; the user submits **Read current state**.
Offering inventory selects the latest version, then links to its exact policy read.
Location edit links preserve the returned operational revision and current profile,
including an inactive value. Request definition reads bind publication and activation
forms to their actual positive revision and current schemas. Required Party input
remains explicit when the read does not itself take a represented Party.

`business_get_info` shows organization profile, public contacts and active locations
with hours. It does not expose concurrency revisions. Location detail now reads the
operational revision, active configured hours and public contacts in one SQL
snapshot, including inactive locations. Location inventory remains the bounded
profile list. Discovery has no current administrative configuration inventory/detail
Query for every control; existing identifiers and current revisions must come from an
owner response. Such forms remain explicit about that requirement. No missing read is
replaced by a fabricated empty collection, revision zero, or automatic grant.

## Role-aware navigation

Navigation is display only. The console learns platform access from the
platform readiness/observability reads it already performs (both `403` means
not a platform operator) and business membership from self-organization
discovery. Business staff land in their business; platform sections are hidden
from them, and nothing about authority is cached as permission. See the console
README for the hint lifetime and the business workspace operation map.

## Interaction and safety

Administrative confirmation follows ADR 0017: recent password proof or verified
WebAuthn, using the same canonical API owner operation. Password confirmation
refreshes only the current session and never manufactures phishing-resistant
assurance. A failed confirmation leaves the pending business command unexecuted;
a successful confirmation preserves its exact revision and idempotency intent.
Recovery completion is explicit and requires ordinary sign-in afterwards when
the current session was created through recovery. Passkey registration remains
optional in normal setup and administration.

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
uses those reads instead of inventing lists or revisions. Schema-defined objects
and lists render as nested fields and add/remove rows. Open configuration documents
remain explicitly advanced; reachability is not a claim that every business task has
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

Initial recovery-binding setup projects the canonical configure operation and its
nullable expected-active-revision default. Leaving that field blank requests
initial creation; it does not invent revision zero or claim an existing binding
is absent. The owning command rejects a conflict. A missing-binding response
links to this setup form, while malformed plans show no completed comparison or
reconciliation action. The setup GET performs no provider or configuration write.

## Guided first-business setup

`/resources/business-setup` projects the existing native organization creation
Command. It reads private, authorized account labels through the native identity
inventory, offers an explicit administrator choice, and forwards the canonical
form through the shared executor. Empty or malformed account pages do not supply
an invented choice. Account pagination occurs before filling the business form.
The successful owner response supplies the organization and represented Party
for the setup link; a partial response supplies no fabricated continuation.
Creation does not prove onboarding readiness or grant the platform operator
implicit membership in the business.

Advanced configuration tasks (the catalog below the clinic setup card) cover
every individual setting. Existing location, service, queue and request
definition choices come from tenant-scoped owner Queries. Current revisions stay
inside loaded edit forms rather than becoming a manual input. Changing the edited
identity requires another read. A stale revision remains an owner conflict and is
never refreshed silently during a mutation or authentication retry.

Location hours/contact replacement forms start with the actual child snapshot,
not an invented empty list. Missing child fields block the edit. Replacing all
opening hours also requires an explicit acknowledgement, including a deliberate
empty schedule. Weekdays use names and canonical date/time fields use browser
controls; timestamps requiring an offset retain it. Native time controls allow
fractional seconds without a whole-second step restriction. Existing time values
with sub-millisecond precision or an offset use an exact text control, because
the browser's time picker would silently clear them. This is preservation of
owner-returned values, not a new time admission or rounding policy.

The shared form projection resolves nested canonical schemas and preserves
omission, false, explicit null and empty collections. Existing fields outside a
known schema fall back to the complete advanced document instead of being erased.
Optional groups and list additions require JavaScript, with a visible explanation
when it is unavailable. Required account/resource choices start without a selected
item; an administrator must make a deliberate choice.

No Party directory is currently exposed. The tenant console therefore resolves
the represented business Party from the signed-in owner's own self-authority
snapshot (`authority_read_self`, the representation with
`operations.manage_profile` scope) and carries it as `authority_party_id`; it is
never typed by a person and remains subject to owner authorization. An explicit
reference from the organization creation result still prefills advanced tasks.

### Guided clinic setup

`/tenants/{organization_id}/setup` (`routes_clinic_setup.py`, form helpers in
`clinic_setup.py`) is the normal owner path; the configuration page links to it
and labels the task catalog as advanced settings. It is a projection of the
owner operations listed in `CLINIC_SETUP_OPERATION_IDS`, resolved by operationId
from the live runtime catalog and sent as JSON with `Idempotency-Key`
`clinic-setup:<form intent>:<part>`. The chains are: profile PATCH + contacts
replace; location create (generated slug key, business or Santo Domingo time
zone) + hours replace with the read `operational_revision` + location contacts;
resource capability ("Provides <service>") + offering with one requirement +
base booking terms (price is required because slots need terms; 0 is free);
exclusive resource with location, capability ids and weekly availability; and
service queue. Before creating, the current owner inventory is read; an item
with the same generated key and name is treated as a resubmission (no
duplicate), a key held by a differently named item moves to `-2`, `-3`, and
identical hours are not replaced. Local phone numbers are written in the
international form the owner requires (+1 for 10-digit numbers); the owner
still validates every value. The finish step shows owner readiness with blocker
codes translated into next actions and the first slots from
`appointments_find_slots` for the next seven days.

With controller policy v8 the owner lacks `organization.manage_profile` and
`queue.configure`: those two steps are refused by the owner and shown as
"the platform administrator has to upgrade" with a skip action. The PostgreSQL
E2E journey `tests/e2e/test_console_clinic_setup_journey.py` runs the whole flow
as a freshly provisioned v8 owner and proves Locations and Appointments
readiness and returned slots. Missing owner readback and
free-form configuration documents still require advanced input. This is a guided
normal setup path, not a claim that every administrative operation can yet be
completed without technical knowledge.
