# Split HTTP deployment Compose renderer

scripts/operations/render_http_deployment.py renders a small Compose file for
the existing request_engine.bootstrap.server:create_app public API and
request_engine.bootstrap.platform_server:create_app private control plane.
Both services use one immutable image@sha256:... reference, run as the image's
unprivileged 10001:10001 account, and receive separate absolute environment
file references. The plan contains no secret values; the renderer does not
create either environment file or deploy/activate the result.

The public API listener is published only on a loopback host address for a host
TLS proxy. The control listener is published only on a declared loopback,
RFC1918 IPv4, or IPv6 ULA address. Wildcard, global, multicast, and DNS-name
bind addresses are rejected. The services use separate Docker bridges and do
not share a Compose network. This prevents direct service-name/container
routing between them. It does **not** prove host-level isolation: Docker
published ports and host routes can still provide paths through the host.
Host firewall policy must deny the public API container/bridge and public
ingress from reaching the private control listener, while permitting only the
approved private proxy/VPN sources. Record the firewall revision in the plan
and verify it from both public and private vantage points using
[network-isolation-acceptance.md](network-isolation-acceptance.md).

Each service accepts forwarded headers only from its separately declared
trusted_proxy_source host IP. A bare address or its exact IPv4 /32 or IPv6 /128
form is accepted; subnet ranges are rejected so unrelated proxy hosts cannot
inherit trust. Determine the source address observed by the container from the
actual host proxy and Docker route. The proxy must overwrite forwarded headers
from the client before forwarding. If a deployment cannot establish that
single-host boundary, do not enable proxy-header trust: use Uvicorn's
--no-proxy-headers and validate the resulting external-origin behavior before
accepting the deployment.

WebAuthn rp_id and HTTPS allowed_origins are explicit plan inputs and are
rendered as non-secret settings for both processes. Choose the actual browser
origins served by the TLS proxy; the renderer checks that they are HTTPS origins
within the relying-party domain. Secrets, database credentials, signing keys,
and other process settings belong in the distinct API and control environment
files, created by the operator with restrictive ownership and permissions.

Example plan:

~~~json
{
  "schema": "request-engine/http-deployment-plan/v1",
  "image": "registry.example/request-engine@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "api_env_file": "/etc/request-engine/api.env",
  "control_env_file": "/etc/request-engine/control.env",
  "public_api": {
    "host_ip": "127.0.0.1",
    "published_port": 18000,
    "trusted_proxy_source": "127.0.0.1"
  },
  "private_control": {
    "host_ip": "10.20.30.40",
    "published_port": 18001,
    "trusted_proxy_source": "10.20.30.41"
  },
  "webauthn": {
    "rp_id": "example.com",
    "allowed_origins": ["https://console.example.com", "https://api.example.com"]
  },
  "firewall_configuration_reference": "host-firewall-change-421"
}
~~~

Render and inspect the result before using it:

~~~sh
uv run python scripts/operations/render_http_deployment.py deployment-plan.json \
  --output compose.generated.yaml
docker compose -f compose.generated.yaml config
~~~

The renderer accepts only an immutable image digest, two different normalized
absolute environment-file paths (without newline, $, %, colon, or
backslash), explicit host addresses, ports and proxy sources, plus bounded
WebAuthn and firewall references. It emits no PostgreSQL or OpenBao service,
host networking, socket mounts, or published database/secrets-administration
ports. Database and secret-provider connectivity, host proxy/TLS, WebAuthn
credential setup, and firewall behavior remain operator-owned deployment work.
The Compose output is a topology preparation artifact, not production
acceptance evidence.
