from pathlib import Path

import pytest

pytestmark = [pytest.mark.architecture, pytest.mark.security]

ROOT = Path(__file__).resolve().parents[2]


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_production_openbao_reference_is_not_dev_mode_or_root_token_bootstrap() -> None:
    compose = _text("deploy/openbao/compose.yaml")
    server = _text("deploy/openbao/openbao.hcl")
    proxy = _text("deploy/openbao/proxy.hcl")

    assert "openbao/openbao:2.6.1" in compose
    assert '["bao", "server"' in compose
    assert '["bao", "proxy"' in compose
    assert "server -dev" not in compose
    assert "BAO_DEV_ROOT_TOKEN_ID" not in compose
    assert "root-token" not in compose.lower()

    # Production server traffic is TLS protected and persistent state is Raft.
    assert 'storage "raft"' in server
    assert "tls_cert_file" in server
    assert "tls_key_file" in server

    # Request Engine-facing proxy authenticates as a workload and injects its
    # auto-auth token; Request Engine itself does not need a static OpenBao token.
    assert 'method "approle"' in proxy
    assert 'use_auto_auth_token = "force"' in proxy
    assert "remove_secret_id_file_after_reading = true" in proxy
    assert "secret_id_response_wrapping_path" in proxy

    # The single-host reference does not publish either listener on all host
    # interfaces.
    assert '"127.0.0.1:8200:8200"' in compose
    assert '"127.0.0.1:8100:8100"' in compose


def test_openbao_runtime_and_control_policies_are_separate_and_prefix_bounded() -> None:
    runtime = _text("deploy/openbao/policies/request-engine-runtime.hcl")
    control = _text("deploy/openbao/policies/request-engine-control.hcl")

    for policy in (runtime, control):
        assert "request-engine/platform/*" in policy
        assert "request-engine/identity-recovery/*" in policy
        assert 'path "*"' not in policy

    assert 'capabilities = ["read"]' in runtime
    assert '"create"' not in runtime
    assert '"update"' not in runtime
    assert '"delete"' not in runtime

    assert '"create"' in control
    assert '"update"' in control
    assert '"delete"' in control


def test_reusable_e2e_secrets_profile_certifies_openbao_not_hashicorp_vault() -> None:
    compose = _text("deploy/reference/compose.e2e.yaml")
    orchestrator = _text("scripts/ci/run_e2e_suite.sh")

    assert "openbao:" in compose
    assert "openbao/openbao:2.6.1" in compose
    assert "hashicorp/vault" not in compose
    assert "secrets) infra+=(openbao)" in orchestrator
    assert "secrets) infra+=(vault)" not in orchestrator
