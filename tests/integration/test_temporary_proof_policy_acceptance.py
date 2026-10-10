"""Opt-in isolated provider proof, not production deployment certification."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
import pytest

from request_engine.platform.secrets.delivery import RecoveryDeliveryRetryable
from request_engine.platform.secrets.openbao_recovery_secret_store import OpenBaoRecoverySecretStore
from request_engine.platform.secrets.temporary_proof_cleanup_acceptance import (
    TemporaryProofExpiryReceipt,
    probe_expired_temporary_proof_destruction,
)
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore

pytestmark = [pytest.mark.integration, pytest.mark.security, pytest.mark.concurrency]
_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize("store_type", [VaultRecoverySecretStore, OpenBaoRecoverySecretStore])
async def test_real_policy_nonreuse_preserves_winner_and_reconciles_cleanup(
    store_type: type[VaultRecoverySecretStore] | type[OpenBaoRecoverySecretStore],
) -> None:
    address = os.environ.get("REQUEST_ENGINE_ISOLATED_PROOF_PROVIDER")
    token = os.environ.get("REQUEST_ENGINE_ISOLATED_PROOF_BOOTSTRAP_TOKEN")
    if address is None or token is None:
        pytest.skip("explicit isolated provider and bootstrap credential required")
    parsed = urlsplit(address)
    assert parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "::1"}
    assert parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
    assert not parsed.username and not parsed.password
    root_headers = {"X-Vault-Token": token}
    async with httpx.AsyncClient(base_url=address, trust_env=False, timeout=5) as admin:
        health = await admin.get("/v1/sys/health")
        assert health.is_success and health.json()["initialized"] and not health.json()["sealed"]
        policies: dict[str, str] = {}
        for label, filename in (
            ("writer", "request-engine-control.hcl"),
            ("janitor", "request-engine-proof-cleanup.hcl"),
        ):
            policy = f"isolated-proof-{label}-{uuid4().hex}"
            loaded = await admin.put(
                f"/v1/sys/policies/acl/{policy}",
                headers=root_headers,
                json={
                    "policy": await asyncio.to_thread(
                        (_ROOT / "deploy/openbao/policies" / filename).read_text,
                    )
                },
            )
            assert loaded.is_success
            created = await admin.post(
                "/v1/auth/token/create",
                headers=root_headers,
                json={"policies": [policy], "no_default_policy": True, "ttl": "5m"},
            )
            assert created.is_success
            policies[label] = created.json()["auth"]["client_token"]
        writer_headers = {"X-Vault-Token": policies["writer"]}
        janitor_headers = {"X-Vault-Token": policies["janitor"]}
        store = store_type(
            address=address,
            token=policies["writer"],
            timeout_seconds=1,
        )
        case = uuid4()
        expiry = datetime.now(UTC) + timedelta(seconds=8)
        first = await store.stage(
            case_id=case, generation=1, secret="isolated-winner", expires_at=expiry
        )
        retained = await store.stage(
            case_id=case,
            generation=1,
            secret="isolated-loser",
            expires_at=expiry + timedelta(hours=1),
        )
        assert first.created and not retained.created and retained.expires_at == first.expires_at
        assert retained.digest == first.digest
        assert first.retention_version is not None
        assert retained.retention_version == first.retention_version
        await store.discard(case_id=case, generation=1)
        assert await store.read(reference=first.reference) == "isolated-winner"
        path = first.reference
        for headers in (writer_headers, janitor_headers):
            assert (
                await admin.delete(f"/v1/secret/metadata/{path}", headers=headers)
            ).status_code == 403
        assert (
            await admin.post(
                f"/v1/secret/destroy/{path}",
                headers=writer_headers,
                json={"versions": [1]},
            )
        ).status_code == 403
        assert (
            await admin.get(f"/v1/secret/data/{path}", headers=janitor_headers)
        ).status_code == 403
        before = await admin.get(f"/v1/secret/metadata/{path}", headers=janitor_headers)
        before.raise_for_status()
        version = before.json()["data"]["versions"]["1"]
        created_at = datetime.fromisoformat(version["created_time"].replace("Z", "+00:00"))
        deletion_at = datetime.fromisoformat(version["deletion_time"].replace("Z", "+00:00"))
        receipt = TemporaryProofExpiryReceipt(path, 1, retained.expires_at, created_at, deletion_at)
        await asyncio.sleep(
            max(0, (expiry + timedelta(seconds=1) - datetime.now(UTC)).total_seconds())
        )
        inspected, release = asyncio.Event(), asyncio.Event()

        class PausedMetadataTransport(httpx.AsyncBaseTransport):
            async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
                response = await admin.send(request)
                await response.aread()
                if request.method == "GET" and not inspected.is_set():
                    inspected.set()
                    await release.wait()
                return response

        async with httpx.AsyncClient(
            base_url=address, transport=PausedMetadataTransport()
        ) as janitor:
            cleanup = asyncio.create_task(
                probe_expired_temporary_proof_destruction(
                    janitor,
                    headers=janitor_headers,
                    receipt=receipt,
                    now=datetime.now(UTC),
                    grace=timedelta(seconds=1),
                    isolated_acceptance=True,
                )
            )
            try:
                await asyncio.wait_for(inspected.wait(), timeout=5)
                # Independently attempt recreation after cleanup inspection, before destroy.
                assert (
                    await admin.delete(
                        f"/v1/secret/metadata/{path}",
                        headers=writer_headers,
                    )
                ).status_code == 403
                with pytest.raises(RecoveryDeliveryRetryable):
                    await store.stage(
                        case_id=case,
                        generation=1,
                        secret="new-live-winner",
                        expires_at=datetime.now(UTC) + timedelta(hours=1),
                    )
            finally:
                release.set()
            assert (await cleanup).outcome == "destroyed"
            assert (
                await probe_expired_temporary_proof_destruction(
                    janitor,
                    headers=janitor_headers,
                    receipt=receipt,
                    now=datetime.now(UTC),
                    grace=timedelta(seconds=1),
                    isolated_acceptance=True,
                )
            ).outcome == "destroyed"
        final = await admin.get(f"/v1/secret/metadata/{path}", headers=janitor_headers)
        final.raise_for_status()
        assert final.json()["data"]["current_version"] == 1
        assert final.json()["data"]["versions"]["1"]["created_time"] == version["created_time"]
        assert final.json()["data"]["versions"]["1"]["destroyed"] is True
