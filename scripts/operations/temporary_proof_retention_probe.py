"""Opt-in real KV-v2 probe: first-version deadline, CAS preservation, soft deletion.

Run only against an explicitly selected test provider. Credentials come from
environment; output contains no secret, token, candidate reference or destination.
"""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from request_engine.platform.secrets.delivery import RecoveryDeliveryPermanent
from request_engine.platform.secrets.vault_secret_store import VaultRecoverySecretStore


async def probe(address: str) -> dict[str, object]:
    token = os.environ["REQUEST_ENGINE_RETENTION_PROBE_TOKEN"]
    store = VaultRecoverySecretStore(
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
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.address)), sort_keys=True))


if __name__ == "__main__":
    main()
