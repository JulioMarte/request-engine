#!/usr/bin/env python3
"""Render a bounded Compose topology for the split public/private HTTP planes."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit


class DeploymentPlanError(ValueError):
    """The deployment plan contains unsafe or incomplete values."""


_DIGEST = re.compile(
    r"(?:[a-z0-9.-]+(?::[0-9]{1,5})?/)?"
    r"[a-z0-9]+(?:[._/-][a-z0-9]+)*@sha256:[0-9a-f]{64}\Z"
)
_RP_ID = re.compile(r"[A-Za-z0-9.-]{1,253}\Z")
_PRIVATE_V4 = tuple(map(ipaddress.ip_network, ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")))
_ULA_V6 = ipaddress.ip_network("fc00::/7")


def _port(value: Any, label: str) -> int:
    if type(value) is not int or not 1 <= value <= 65535:
        raise DeploymentPlanError(f"{label} must be an integer from 1 through 65535")
    return value


def _proxy_host(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise DeploymentPlanError(f"{label} must be one explicit proxy host IP")
    try:
        network = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise DeploymentPlanError(f"{label} must be one explicit proxy host IP") from exc
    if network.is_unspecified or network.is_multicast or network.prefixlen == 0:
        raise DeploymentPlanError(f"{label} cannot trust all proxy sources")
    if network.prefixlen != network.max_prefixlen:
        raise DeploymentPlanError(f"{label} must identify one host (IPv4 /32 or IPv6 /128)")
    return str(network)


def _host_ip(value: Any, label: str, *, public: bool) -> str:
    if not isinstance(value, str):
        raise DeploymentPlanError(f"{label} must be an IP literal")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise DeploymentPlanError(f"{label} must be an IP literal") from exc
    if address.is_unspecified or address.is_multicast:
        raise DeploymentPlanError(f"{label} cannot be wildcard or multicast")
    if public:
        if not address.is_loopback:
            raise DeploymentPlanError("public_api.host_ip must be loopback-only behind host TLS")
    elif not (
        address.is_loopback
        or (isinstance(address, ipaddress.IPv4Address) and any(address in n for n in _PRIVATE_V4))
        or (isinstance(address, ipaddress.IPv6Address) and address in _ULA_V6)
    ):
        raise DeploymentPlanError("private_control.host_ip must be loopback, RFC1918, or IPv6 ULA")
    return str(address)


def _env_file(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or "\n" in value
        or "\r" in value
        or "\x00" in value
        or any(token in value for token in ("$", "%", ":"))
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/")[1:])
    ):
        raise DeploymentPlanError(
            f"{label} must be an absolute normalized path without newline, $, %, "
            "colon, or backslash"
        )
    return value


def _webauthn(value: Any) -> tuple[str, list[str]]:
    if not isinstance(value, dict):
        raise DeploymentPlanError("webauthn requires rp_id and allowed_origins")
    settings = cast(dict[str, Any], value)
    if set(settings) != {"rp_id", "allowed_origins"}:
        raise DeploymentPlanError("webauthn requires rp_id and allowed_origins")
    rp_id = settings["rp_id"]
    origins = settings["allowed_origins"]
    if not isinstance(rp_id, str) or not _RP_ID.fullmatch(rp_id) or rp_id.startswith("."):
        raise DeploymentPlanError("webauthn.rp_id must be a bounded relying-party host")
    if not isinstance(origins, list):
        raise DeploymentPlanError("webauthn.allowed_origins must contain 1 through 8 origins")
    origins = cast(list[Any], origins)
    if not 1 <= len(origins) <= 8:
        raise DeploymentPlanError("webauthn.allowed_origins must contain 1 through 8 origins")
    normalized: list[str] = []
    for origin in origins:
        if not isinstance(origin, str) or any(
            character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F
            for character in origin
        ):
            raise DeploymentPlanError("WebAuthn origins must be HTTPS origins")
        try:
            parsed = urlsplit(origin)
            hostname = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise DeploymentPlanError("WebAuthn origins must be valid HTTPS origins") from exc
        canonical_origin = origin.rstrip("/")
        if (
            parsed.scheme != "https"
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (
                hostname.lower() != rp_id.lower()
                and not hostname.lower().endswith("." + rp_id.lower())
            )
            or canonical_origin in normalized
        ):
            raise DeploymentPlanError(
                "WebAuthn origins must be unique HTTPS origins within the relying-party domain"
            )
        normalized.append(canonical_origin)
    return rp_id, normalized


def validate_plan(plan: Any) -> dict[str, Any]:
    required = {
        "schema",
        "image",
        "api_env_file",
        "control_env_file",
        "public_api",
        "private_control",
        "webauthn",
        "firewall_configuration_reference",
    }
    if not isinstance(plan, dict):
        raise DeploymentPlanError("plan must contain exactly the declared deployment fields")
    values = cast(dict[str, Any], plan)
    if set(values) != required:
        raise DeploymentPlanError("plan must contain exactly the declared deployment fields")
    if values["schema"] != "request-engine/http-deployment-plan/v1":
        raise DeploymentPlanError("unsupported deployment plan schema")
    image = values["image"]
    if not isinstance(image, str) or not _DIGEST.fullmatch(image):
        raise DeploymentPlanError("image must be pinned to an immutable sha256 digest")
    api_env = _env_file(values["api_env_file"], "api_env_file")
    control_env = _env_file(values["control_env_file"], "control_env_file")
    if api_env == control_env:
        raise DeploymentPlanError("API and control plane must use separate environment files")
    api = values["public_api"]
    control = values["private_control"]
    if not isinstance(api, dict) or not isinstance(control, dict):
        raise DeploymentPlanError("public_api and private_control must be objects")
    api = cast(dict[str, Any], api)
    control = cast(dict[str, Any], control)
    if set(api) != {"host_ip", "published_port", "trusted_proxy_source"}:
        raise DeploymentPlanError(
            "public_api requires host_ip, published_port, and trusted_proxy_source"
        )
    if set(control) != {"host_ip", "published_port", "trusted_proxy_source"}:
        raise DeploymentPlanError(
            "private_control requires host_ip, published_port, and trusted_proxy_source"
        )
    api_ip = _host_ip(api["host_ip"], "public_api.host_ip", public=True)
    control_ip = _host_ip(control["host_ip"], "private_control.host_ip", public=False)
    api_port = _port(api["published_port"], "public_api.published_port")
    control_port = _port(control["published_port"], "private_control.published_port")
    if (api_ip, api_port) == (control_ip, control_port):
        raise DeploymentPlanError("public and private listeners cannot share a host endpoint")
    proxy_source = _proxy_host(api["trusted_proxy_source"], "public_api.trusted_proxy_source")
    control_proxy_source = _proxy_host(
        control["trusted_proxy_source"], "private_control.trusted_proxy_source"
    )
    rp_id, origins = _webauthn(values["webauthn"])
    firewall_ref = values["firewall_configuration_reference"]
    if not isinstance(firewall_ref, str) or not firewall_ref.strip() or len(firewall_ref) > 256:
        raise DeploymentPlanError("firewall_configuration_reference must be a bounded reference")
    return {
        "image": image,
        "api_env_file": api_env,
        "control_env_file": control_env,
        "api_ip": api_ip,
        "api_port": api_port,
        "control_ip": control_ip,
        "control_port": control_port,
        "trusted_proxy_source": proxy_source,
        "control_trusted_proxy_source": control_proxy_source,
        "rp_id": rp_id,
        "allowed_origins": origins,
        "firewall_configuration_reference": firewall_ref,
    }


def render_compose(plan: Any) -> str:
    config = validate_plan(plan)

    def q(value: Any) -> str:
        return json.dumps(value, ensure_ascii=True)

    api_command = [
        "uvicorn",
        "request_engine.bootstrap.server:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--proxy-headers",
        f"--forwarded-allow-ips={config['trusted_proxy_source']}",
    ]
    control_command = [
        "uvicorn",
        "request_engine.bootstrap.platform_server:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8001",
        "--proxy-headers",
        f"--forwarded-allow-ips={config['control_trusted_proxy_source']}",
    ]
    lines = [
        "services:",
        "  api:",
        f"    image: {q(config['image'])}",
        '    user: "10001:10001"',
        "    read_only: true",
        '    cap_drop: ["ALL"]',
        '    security_opt: ["no-new-privileges:true"]',
        f"    command: {q(api_command)}",
        "    env_file:",
        f"      - {q(config['api_env_file'])}",
        "    environment:",
        f"      REQUEST_ENGINE_WEBAUTHN_RP_ID: {q(config['rp_id'])}",
        f"      REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS: {q(','.join(config['allowed_origins']))}",
        "    ports:",
        "      - target: 8000",
        f"        published: {q(str(config['api_port']))}",
        f"        host_ip: {q(config['api_ip'])}",
        "        protocol: tcp",
        "    networks: [public_edge]",
        "    restart: unless-stopped",
        "  control-plane:",
        f"    image: {q(config['image'])}",
        '    user: "10001:10001"',
        "    read_only: true",
        '    cap_drop: ["ALL"]',
        '    security_opt: ["no-new-privileges:true"]',
        f"    command: {q(control_command)}",
        "    env_file:",
        f"      - {q(config['control_env_file'])}",
        "    environment:",
        f"      REQUEST_ENGINE_WEBAUTHN_RP_ID: {q(config['rp_id'])}",
        f"      REQUEST_ENGINE_WEBAUTHN_ALLOWED_ORIGINS: {q(','.join(config['allowed_origins']))}",
        "    ports:",
        "      - target: 8001",
        f"        published: {q(str(config['control_port']))}",
        f"        host_ip: {q(config['control_ip'])}",
        "        protocol: tcp",
        "    networks: [private_control]",
        "    restart: unless-stopped",
        "networks:",
        "  public_edge:",
        "    driver: bridge",
        "  private_control:",
        "    driver: bridge",
        "x-request-engine-acceptance:",
        '  schema: "request-engine/http-deployment-manifest/v1"',
        f"  firewall_configuration_reference: {q(config['firewall_configuration_reference'])}",
        "  host_isolation_certified: false",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.plan.stat().st_size > 64 * 1024:
            raise DeploymentPlanError("plan file exceeds 64 KiB")
        rendered = render_compose(json.loads(args.plan.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, DeploymentPlanError) as exc:
        raise SystemExit(f"HTTP deployment plan rejected: {exc}") from exc
    if args.output is None:
        print(rendered, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
