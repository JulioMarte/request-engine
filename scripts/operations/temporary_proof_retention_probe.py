"""Opt-in isolated KV-v2 probe: expiry, CAS preservation, explicit-version destroy.

Run only against an explicitly selected test provider. Credentials come from
environment; output contains no secret, token, candidate reference or destination.
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from request_engine.platform.secrets.delivery import RecoveryDeliveryPermanent
from request_engine.platform.secrets.openbao_recovery_secret_store import OpenBaoRecoverySecretStore
from request_engine.platform.secrets.temporary_proof_cleanup_acceptance import (
    TemporaryProofExpiryReceipt,
    probe_expired_temporary_proof_destruction,
)
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore


async def probe(address: str, provider: str = "vault") -> dict[str, object]:
    parsed = urlsplit(address)
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname not in ("localhost", "127.0.0.1", "::1")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("retention probe requires an isolated loopback provider")
    token = os.environ["REQUEST_ENGINE_RETENTION_PROBE_TOKEN"]
    store_type = VaultRecoverySecretStore if provider == "vault" else OpenBaoRecoverySecretStore
    store = store_type(
        address=address,
        token=token,
        timeout_seconds=1,
        path_prefix=f"request-engine/temporary-proof-retention-probe/{uuid4()}",
    )
    case_id = uuid4()
    expiry = datetime.now(UTC) + timedelta(seconds=10)
    first = await store.stage(
        case_id=case_id, generation=1, secret="first-test-proof", expires_at=expiry
    )
    replay = await store.stage(
        case_id=case_id, generation=1, secret="competing-test-proof", expires_at=expiry
    )
    assert first.created and not replay.created and first.digest == replay.digest
    assert await store.read(reference=first.reference) == "first-test-proof"
    async with httpx.AsyncClient(base_url=address, trust_env=False) as client:
        metadata = await client.get(
            f"/v1/secret/metadata/{first.reference}", headers={"X-Vault-Token": token}
        )
        metadata.raise_for_status()
        version = metadata.json()["data"]["versions"]["1"]
        deletion = datetime.fromisoformat(version["deletion_time"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(version["created_time"].replace("Z", "+00:00"))
        assert datetime.now(UTC) < deletion <= expiry
        deadline = expiry + timedelta(seconds=5)
        while datetime.now(UTC) < deadline:
            response = await client.get(
                f"/v1/secret/data/{first.reference}", headers={"X-Vault-Token": token}
            )
            if response.status_code == 404:
                break
            response.raise_for_status()
            await asyncio.sleep(0.2)
        else:
            raise RuntimeError("Provider version remained readable beyond expiry")
        cleanup_receipt = TemporaryProofExpiryReceipt(
            reference=first.reference,
            version=1,
            expires_at=first.expires_at,
            created_at=created,
            deletion_at=deletion,
        )
        wait_seconds = (expiry + timedelta(seconds=1) - datetime.now(UTC)).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
        for _ in range(2):
            cleanup = await probe_expired_temporary_proof_destruction(
                client,
                headers={"X-Vault-Token": token},
                receipt=cleanup_receipt,
                now=datetime.now(UTC),
                grace=timedelta(seconds=1),
                isolated_acceptance=True,
            )
            assert cleanup.outcome == "destroyed"
    try:
        await store.read(reference=first.reference)
    except RecoveryDeliveryPermanent:
        pass
    else:
        raise RuntimeError("Expired proof remained readable")
    return {
        "schema": "request-engine/temporary-proof-retention-probe/v1",
        "first_version_deadline_verified": True,
        "cas_winner_preserved": True,
        "expired_version_not_readable": True,
        "physical_destruction_proven": False,
        "provider": provider,
        "explicit_version_destroy_confirmed": True,
        "destroy_retry_reconciled": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--provider", choices=("vault", "openbao"), default="vault")
    args = parser.parse_args()
    try:
        output = asyncio.run(probe(args.address, args.provider))
    except Exception:
        parser.exit(1, "temporary_proof_retention_probe_failed\n")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
