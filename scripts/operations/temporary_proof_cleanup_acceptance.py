"""Opt-in loopback acceptance tool; not a production retention scheduler.

Trusted JSON receipts must contain reference, version, expires_at, created_at and
deletion_at from the retained version. Never put plaintext proofs in the manifest.
"""

import argparse
import asyncio
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from request_engine.platform.secrets.temporary_proof_cleanup_acceptance import (
    TemporaryProofExpiryReceipt,
    probe_expired_temporary_proof_destruction,
)


async def run(address: str, manifest: Path, grace_seconds: int) -> list[dict[str, str]]:
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
        raise ValueError("cleanup acceptance tool requires an isolated loopback provider")
    raw = json.loads(await asyncio.to_thread(manifest.read_text, encoding="utf-8"))
    receipts = [
        TemporaryProofExpiryReceipt(
            reference=item["reference"],
            version=item["version"],
            expires_at=datetime.fromisoformat(item["expires_at"]),
            created_at=datetime.fromisoformat(item["created_at"]),
            deletion_at=datetime.fromisoformat(item["deletion_at"]),
        )
        for item in raw
    ]
    token = os.environ["REQUEST_ENGINE_RETENTION_CLEANUP_TOKEN"]
    results: list[dict[str, str]] = []
    async with httpx.AsyncClient(base_url=address, timeout=5, trust_env=False) as client:
        for receipt in receipts:
            outcome = await probe_expired_temporary_proof_destruction(
                client,
                headers={"X-Vault-Token": token},
                receipt=receipt,
                now=datetime.now(UTC),
                grace=timedelta(seconds=grace_seconds),
                isolated_acceptance=True,
            )
            results.append(asdict(outcome))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--grace-seconds", type=int, default=3600)
    parser.add_argument("--allow-isolated-destroy", action="store_true", required=True)
    args = parser.parse_args()
    if args.grace_seconds < 1:
        parser.error("positive grace required")
    try:
        output = asyncio.run(run(args.address, args.manifest, args.grace_seconds))
    except Exception:
        # No traceback/manifest/provider body can expose a secret reference.
        parser.exit(1, "temporary_proof_cleanup_failed\n")
    print(json.dumps({"schema": "temporary-proof-cleanup/v1", "results": output}))


if __name__ == "__main__":
    main()
