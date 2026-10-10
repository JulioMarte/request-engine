# Public/private network acceptance

Status: deployment acceptance procedure; no host/network has been accepted.
Owner: deployment operator. Complements
[HTTP deployment](../architecture/http-runtime-deployment.md) and gate O-01 in
the [readiness report](../testing/pr137-api-production-readiness-2026-10-06.md).

## Declare the topology before probing

Record source SHA/image digest, DNS names, ingress addresses, TLS issuer/expiry,
public and private listeners, database/OpenBao/Collector ports, firewall/security
group and proxy configuration revisions, trusted proxy CIDRs, WebAuthn RP ID
and allowed HTTPS origins. Name the authorized private access path and the
machines/networks that will originate positive and negative probes. Use approved
test hosts only, without scanning unrelated addresses.

The public data plane and private control plane must have separate exposure.
Application authentication does not substitute for network isolation. Docker's
internal network and CI sinks demonstrate laboratory boundaries only. Host
published ports, IPv6, alternate DNS/address paths and upstream proxy routes
must be checked independently.

## Probe matrix

| Probe source | Target/check | Required result |
| --- | --- | --- |
| External machine outside VPN/private network | Public HTTPS readiness | Valid hostname/TLS and expected public readiness; no private configuration |
| Same external machine | Control-plane hostname and direct host control port | Connection/routing denied; HTTP 401/403 proves reachability and fails isolation |
| Same external machine | Each declared database, OpenBao and Collector host listener | No transport access to private listeners; test IPv4 and IPv6 when routed |
| Authorized private machine | Private control HTTPS/readiness | Valid TLS and intended authenticated access |
| Authorized private machine, no credentials | Private administrative operation | Authentication rejected with no side effects or secret leakage |
| Public ingress | Known private route, including setup/control routes | No proxy route to private service; app response alone cannot prove firewall policy |
| Public ingress | Spoofed forwarded host/protocol/client-address headers | Trusted origin/client identity cannot be manufactured by untrusted headers |
| Test browser/client | Valid passkey with disallowed origin/RP | Authentication rejected; no credential/session changes |
| Both ingress surfaces after legitimate first claim | Setup re-entry | Closed setup; no new platform owner/session issued |

Use exact listener addresses from the declared topology, not guessed defaults.
For example, from the designated external host:

```bash
curl --connect-timeout 5 --max-time 10 --fail --silent --show-error \
  --write-out 'http_code=%{http_code}\n' \
  https://PUBLIC_HOST/health/ready
nc -vz -w 5 PRIVATE_HOST DECLARED_PRIVATE_PORT
```

Substitute operator-reviewed values; never use `curl -k`. The private connection
probe must fail at transport/routing. Capture its exit status and associate it
with timestamped firewall/ingress observations. DNS failure alone is insufficient.
Record the HTTP status as well as curl's exit status: exit 22 for a 401/403
is an HTTP rejection from a reachable service, not a blocked connection.
Also test known reachable host addresses from the same external machine. For
HTTPS direct-address checks preserve Host/SNI via `curl --resolve`; certificate
failure alone does not prove a private port is inaccessible.

Verify actual listener/publish/firewall configuration on the host separately.
Avoid dumping complete container environments or credentials into evidence.
Run database privilege checks with each real runtime LOGIN: no superuser,
BYPASSRLS, object ownership, elevated memberships or unrelated capabilities.
Positive private access must succeed while negative public access fails; a
service that is stopped everywhere is not proof of a correct access boundary.

## Evidence and release decision

Save candidate/configuration identities, UTC timestamps, source network/address,
exact declared target, result/exit status and matching server/firewall observation.
Record positive availability checks alongside every negative trial. Redact bearer
headers, database URLs, tokens and personal identifiers. Persist configuration
references and test outcomes, not broad debug dumps.

Repeat after proxy, firewall, routing, DNS, container publishing or host changes.
A missing source network, untested routed address family, reachable private
listener, insecure TLS or unverified effective LOGIN permissions leaves O-01
pending. No production acceptance is inferred from CI or local loopback tests.

## Executable listener observations

`scripts/operations/network_acceptance_probe.py PLAN --output EVIDENCE` checks
only declared IP literals and ports (at most 64, each with a finite deadline).
Run separately on the approved public and private machines. A plan has this
shape, with operator-reviewed values:

```json
{
  "schema": "request-engine/network-plan/v1",
  "candidate": "exact-source-sha-and-image-digest",
  "configuration_reference": "reviewed-ingress-firewall-revision",
  "source_reference": "approved-external-machine",
  "vantage": "public",
  "timeout_seconds": 3,
  "endpoints": [
    {"id": "control-ipv4", "address": "192.0.2.10", "port": 443,
     "protocol": "tls", "server_name": "control.example.com", "expected": "blocked"}
  ]
}
```

The documentation address must be replaced; the tool does not discover hosts
or scan ports. Declare every routed IPv4/IPv6 listener explicitly. For public
HTTPS and the private positive baseline, use `expected: "reachable"`; TLS
requires a verified certificate matching `server_name` on the pinned IP. A TCP
handshake always fails a blocked expectation, including TLS rejection/timeout.
DNS errors cannot masquerade as isolation because targets are IP literals.
Refusal/timeout records an observation, not proof of firewall policy. Match
every negative listener with its positive private baseline and effective host
configuration review. Evidence deliberately remains uncertified and marks
those independent checks as required. HTTP route/proxy and LOGIN checks from
the matrix above remain separate acceptance trials.
