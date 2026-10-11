# Local panel: optional real delivery services

Development only. This is not production deployment or a claim that every
dashboard journey works. PowerShell 7.4+, Docker and the normal launcher database
prerequisites are required. The launcher checks migration parity; it never
upgrades or resets the database.

```powershell
./scripts/dev/run_local_panel.ps1 -ConsolePort 8012 -WithDelivery
```

OpenBao 2.6.1 and Mailpit v1.27 listen only on loopback ports 58241, 58242 and
58243, respectively. Ports 58239/58240 belong to independent provider tests and
are not touched. Containers `request-engine-panel-dev-openbao` and
`request-engine-panel-dev-mailpit` have an ownership label; unrelated containers
are rejected. Reruns reuse these containers and reject different port mappings.

OpenBao dev mode is unsealed and memory-backed: a server restart loses secrets.
Keep it running while testing existing invitations. Removing/restarting it can
invalidate proof references already recorded in PostgreSQL. Mailpit is a local
capture inbox, not delivery to external recipients; its UI contains sensitive
recovery/invitation links. Do not expose, forward, export or share it.

The bootstrap root credential is random, stored only in the development
container environment and process memory, never a command argument or file.
Container logs are disabled because dev-mode startup prints the root credential.
Docker administrators can inspect container environments: this is not a secret
boundary against local administrators. Application tokens last eight hours,
are nonrenewable, omit the default policy, and are never printed. Restart the
panel to issue fresh application tokens before expiry. The control process uses
the repository control policy; runtime uses read plus proof-writer policies,
not managed-secret write or temporary-proof destroy/metadata-delete permission.
The inherited Vault configuration is cleared when this option selects OpenBao.

## Delivery worker: prerequisite, not silently simulated

The launcher enables real HTTP-side proof issuance and direct SMTP settings;
**it does not start a worker or claim queued invitation mail has been sent**.
Complete the platform setup first, then provision a genuine integration
principal with the current owner HTTP APIs and appropriate authority. Do not
insert a principal/permissions using SQL just to satisfy the worker.

The existing `request_engine.bootstrap.reference_worker_factory:create_worker`
requires `REQUEST_ENGINE_WORKER_PRINCIPAL_ID`, a least-privilege worker login
(`REQUEST_ENGINE_WORKER_DATABASE_URL`, not the superuser/app login),
`REQUEST_ENGINE_APP_DATABASE_URL` and an actual
`REQUEST_ENGINE_OUTBOX_PUBLISHER_FACTORY`. With the repository HTTP publisher,
configure `REQUEST_ENGINE_OUTBOX_PUBLISH_URL` for a real event receiver.
There is no honest automatic worker start until these are available. No mock
sink, no no-op publisher and no manufactured business authority is supplied.

Configure that worker with the same OpenBao endpoint, runtime/proof-writer
policies and SMTP settings as the panel. A trusted local PowerShell session can
dot-source `scripts/dev/local_panel_delivery.ps1`, assign (never print) the
result of `Start-PanelLocalDelivery` and pass its `RuntimeToken` via the child
process environment, not command arguments. The invitation acceptance base URL
must be `http://localhost:8012/staff-invitations` when using console port 8012.
Tokens must not be copied into scripts, logs or persisted environment files.

Use the existing worker CLI with the reference factory only after all these
prerequisites are satisfied. A queued invitation remains pending until the
worker actually processes it. SMTP acceptance does not prove a recipient read
the message. Native recovery reset links require their own correct canonical
reset URL; this launcher does not fabricate one.

Once the four required settings above are present in your trusted shell's
environment (do not put credentials in shell arguments/history), the guarded
development helper starts that **same** existing worker composition:

```powershell
./scripts/dev/run_local_delivery_worker.ps1 -WithDelivery -ConsolePort 8012
```

The helper requires a nonzero integration-principal UUID and a real loopback
outbox receiver; those syntactic guards do not prove the principal's authority.
Owner validation and worker startup remain authoritative. It uses default
provider ports only and refuses missing prerequisites before starting providers.
It does not provision the worker database login, apply migrations or grant
permissions. Do not run twice concurrently; stop the existing worker deliberately
before restarting. Launch is not health or delivery evidence.

## Focal acceptance check

```powershell
./scripts/dev/test_local_panel_delivery.ps1 -RunRealProviders
```

This starts/reuses only the owned development providers, performs real KV v2
write/read and verifies a first-version expiry, rejects forbidden metadata
deletion/destruction and managed-secret writes, sends nonsecret SMTP mail and
checks Mailpit's actual inbox. It does not touch PostgreSQL, test worker
authorization or certify invitation acceptance. Probe expiry is soft deletion,
not physical destruction or backup erasure. Containers remain available for
manual testing; deleting them is an explicit developer decision and loses their
test secrets/mail. Loopback is not production certification (a tunnel could
reach production); select only the named, owned, isolated dev containers.
