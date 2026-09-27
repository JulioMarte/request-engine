#!/usr/bin/env python3
"""Exercise P7 secret CAS/concurrency guarantees against a real OpenBao endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from request_engine.platform.secrets.openbao_secret_store import OpenBaoPlatformSecretStore
from request_engine.platform.secrets.platform_store import (
    PlatformSecretConflict,
    PlatformSecretNotFound,
    PlatformSecretStore,
)


class OpenBaoAcceptanceError(RuntimeError):
    pass


async def run_acceptance(
    store: PlatformSecretStore,
    *,
    secret_id: UUID,
) -> dict[str, object]:
    initial_operation = uuid4()
    first = await store.write(
        secret_id=secret_id,
        value=f"p7-openbao-initial-{uuid4()}",
        expected_version=None,
        operation_id=initial_operation,
    )
    if first.version <= 0:
        raise OpenBaoAcceptanceError("initial OpenBao write returned an invalid version")

    contenders = (
        (uuid4(), f"p7-openbao-contender-a-{uuid4()}"),
        (uuid4(), f"p7-openbao-contender-b-{uuid4()}"),
    )

    async def rotate(operation_id: UUID, value: str) -> tuple[UUID, str, int]:
        metadata = await store.write(
            secret_id=secret_id,
            value=value,
            expected_version=first.version,
            operation_id=operation_id,
        )
        return operation_id, value, metadata.version

    results = await asyncio.gather(
        *(rotate(operation_id, value) for operation_id, value in contenders),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, tuple)]
    conflicts = [result for result in results if isinstance(result, PlatformSecretConflict)]
    unexpected = [
        result
        for result in results
        if not isinstance(result, (tuple, PlatformSecretConflict))
    ]
    if len(successes) != 1 or len(conflicts) != 1 or unexpected:
        raise OpenBaoAcceptanceError(
            "OpenBao CAS race did not produce exactly one winner and one conflict"
        )

    winner_operation, winner_value, winner_version = successes[0]
    if winner_version <= first.version:
        raise OpenBaoAcceptanceError("winning OpenBao rotation did not advance the version")

    resolved = await store.resolve(secret_id=secret_id)
    metadata = await store.metadata(secret_id=secret_id)
    if resolved != winner_value:
        raise OpenBaoAcceptanceError("OpenBao resolved value does not match CAS winner")
    if metadata.version != winner_version or metadata.operation_id != winner_operation:
        raise OpenBaoAcceptanceError("OpenBao metadata does not identify the CAS winner")

    await store.revoke(secret_id=secret_id)
    try:
        await store.resolve(secret_id=secret_id)
    except PlatformSecretNotFound:
        revoked = True
    else:
        revoked = False
    if not revoked:
        raise OpenBaoAcceptanceError("revoked OpenBao acceptance secret remained readable")

    return {
        "schema": "request-engine/openbao-operational-acceptance/v1",
        "outcome": "accepted",
        "completed_at": datetime.now(UTC).isoformat(),
        "secret_id": str(secret_id),
        "initial_version": first.version,
        "winning_version": winner_version,
        "exactly_one_cas_winner": True,
        "conflicting_writer_rejected": True,
        "winner_operation_marker_verified": True,
        "winner_value_resolution_verified": True,
        "revocation_verified": True,
        "secret_value_persisted_in_evidence": False,
    }


def _store(args: argparse.Namespace) -> OpenBaoPlatformSecretStore:
    token = None
    if args.token_env is not None:
        token = os.environ.get(args.token_env)
        if token is None or not token.strip():
            raise OpenBaoAcceptanceError(
                f"required OpenBao token environment variable is missing: {args.token_env}"
            )
    return OpenBaoPlatformSecretStore(
        address=args.address,
        token=token,
        mount=args.mount,
        path_prefix=args.path_prefix,
        namespace=args.namespace,
        timeout_seconds=args.timeout_seconds,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--token-env")
    parser.add_argument("--mount", default="secret")
    parser.add_argument("--path-prefix", default="request-engine/acceptance")
    parser.add_argument("--namespace")
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        evidence = asyncio.run(run_acceptance(_store(args), secret_id=uuid4()))
    except (OpenBaoAcceptanceError, ValueError) as exc:
        raise SystemExit(f"OpenBao operational acceptance failed: {exc}") from exc
    rendered = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
