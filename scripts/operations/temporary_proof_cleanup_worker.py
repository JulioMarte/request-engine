"""Explicit, bounded retention pass; disabled unless operator admission is current."""

import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from request_engine.bootstrap.outbound_fence import OutboundSideEffectFence
from request_engine.platform.db.session import create_postgres_engine, create_session_factory
from request_engine.platform.secrets.temporary_proof_cleanup_admission import (
    TemporaryCleanupAdmission,
)
from request_engine.platform.secrets.temporary_proof_cleanup_worker import (
    TemporaryProofCleanupWorker,
)


async def run(artifact: Path, maximum: int) -> dict[str, int]:
    admission = TemporaryCleanupAdmission.load(artifact)
    fence = OutboundSideEffectFence.from_environment()
    engine = create_postgres_engine(os.environ["REQUEST_ENGINE_RETENTION_WORKER_DATABASE_URL"])
    counts: dict[str, int] = {}
    try:
        async with httpx.AsyncClient(
            base_url=admission.provider_origin, timeout=5, trust_env=False, follow_redirects=False
        ) as client:
            worker = TemporaryProofCleanupWorker(
                create_session_factory(engine),
                client,
                admission=admission,
                token=os.environ["REQUEST_ENGINE_RETENTION_CLEANUP_TOKEN"],
                outbound_fenced=fence.fenced,
            )
            for _ in range(maximum):
                outcome = await worker.run_once()
                counts[outcome] = counts.get(outcome, 0) + 1
                if outcome == "idle":
                    break
    finally:
        await engine.dispose()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--admission", required=True, type=Path)
    parser.add_argument("--maximum", type=int, default=1)
    parser.add_argument("--enable-admitted-cleanup", action="store_true")
    args = parser.parse_args()
    if not args.enable_admitted_cleanup or not 1 <= args.maximum <= 100:
        parser.error("explicit admission opt-in and maximum 1..100 required")
    try:
        output = asyncio.run(run(args.admission, args.maximum))
    except Exception:
        parser.exit(1, "temporary_proof_cleanup_worker_failed\n")
    print(json.dumps({"schema": "temporary-proof-cleanup-worker/v1", "outcomes": output}))


if __name__ == "__main__":
    main()
