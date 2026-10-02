"""Independent provider metadata oracle protects live/legacy versions and retries."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from request_engine.platform.secrets.temporary_proof_cleanup_acceptance import (
    TemporaryProofExpiryReceipt,
    probe_expired_temporary_proof_destruction,
)

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 2, tzinfo=UTC)


def receipt() -> TemporaryProofExpiryReceipt:
    return TemporaryProofExpiryReceipt(
        reference=f"request-engine/identity-recovery/{uuid4()}/1",
        version=1,
        created_at=NOW - timedelta(hours=3),
        deletion_at=NOW - timedelta(hours=2),
        expires_at=NOW - timedelta(hours=1),
    )


def metadata(target: TemporaryProofExpiryReceipt) -> dict[str, object]:
    return {
        "created_time": target.created_at.isoformat(),
        "deletion_time": target.deletion_at.isoformat(),
        "destroyed": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguity", [None, "transport", 503])
async def test_only_expired_explicit_version_destroyed_and_retry_reconciles(
    ambiguity: object,
) -> None:
    target = receipt()
    old = metadata(target)
    live = {
        "created_time": NOW.isoformat(),
        "deletion_time": (NOW + timedelta(days=1)).isoformat(),
        "destroyed": False,
    }
    posted: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method != "DELETE"
        if request.method == "POST":
            posted.append(json.loads(request.content))
            old["destroyed"] = True
            old["deletion_time"] = ""  # Some providers clear soft-deletion timestamp on destroy.
            if ambiguity == "transport":
                raise httpx.ReadError("private-provider-sentinel", request=request)
            return httpx.Response(503 if ambiguity == 503 else 204)
        return httpx.Response(200, json={"data": {"versions": {"1": old, "2": live}}})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:58200", transport=httpx.MockTransport(handler)
    ) as client:
        for _ in range(2):
            result = await probe_expired_temporary_proof_destruction(
                client,
                headers={},
                receipt=target,
                now=NOW,
                grace=timedelta(seconds=1),
                isolated_acceptance=True,
            )
            assert result.outcome == "destroyed"
            assert target.reference not in repr(result)
    assert posted == [{"versions": [1]}]
    assert live["destroyed"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect", ["live", "legacy", "malformed", "replacement", "manual-delete", "grace"]
)
async def test_unverified_or_unexpired_proof_never_destroyed(defect: str) -> None:
    target = receipt()
    version = metadata(target)
    if defect == "live":
        target = replace(target, expires_at=NOW + timedelta(hours=1))
    elif defect == "grace":
        target = replace(target, expires_at=NOW - timedelta(microseconds=1))
    elif defect == "legacy":
        version["deletion_time"] = ""
    elif defect == "malformed":
        version["destroyed"] = "false"
    elif defect == "replacement":
        version["created_time"] = (NOW - timedelta(hours=4)).isoformat()
    else:
        version["deletion_time"] = (NOW - timedelta(minutes=30)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"data": {"versions": {"1": version}}})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:58200", transport=httpx.MockTransport(handler)
    ) as client:
        result = await probe_expired_temporary_proof_destruction(
            client,
            headers={},
            receipt=target,
            now=NOW,
            grace=timedelta(seconds=1),
            isolated_acceptance=True,
        )
    assert result.outcome in ("retained", "unverified")


@pytest.mark.asyncio
async def test_ambiguous_unconfirmed_destroy_is_unresolved_and_next_call_reinspects() -> None:
    target = receipt()
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.method)
        if request.method == "POST":
            return httpx.Response(503, text="private-provider-sentinel")
        return httpx.Response(200, json={"data": {"versions": {"1": metadata(target)}}})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:58200", transport=httpx.MockTransport(handler)
    ) as client:
        result = await probe_expired_temporary_proof_destruction(
            client,
            headers={},
            receipt=target,
            now=NOW,
            grace=timedelta(seconds=1),
            isolated_acceptance=True,
        )
    assert result.outcome == "unresolved"
    assert requests == ["GET", "POST", "GET"]


@pytest.mark.parametrize(
    "path",
    [
        "request-engine/platform/key/1",
        "request-engine/identity-recovery/../1",
        "request-engine/identity-recovery/x/1",
    ],
)
def test_namespace_is_closed(path: str) -> None:
    with pytest.raises(ValueError):
        replace(receipt(), reference=path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "address, opt_in", [("https://provider.test", True), ("http://127.0.0.1:58200", False)]
)
async def test_production_or_missing_opt_in_rejected_before_io(address: str, opt_in: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No provider I/O permitted")

    async with httpx.AsyncClient(
        base_url=address, transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(ValueError, match="isolated loopback"):
            await probe_expired_temporary_proof_destruction(
                client,
                headers={},
                receipt=receipt(),
                now=NOW,
                grace=timedelta(seconds=1),
                isolated_acceptance=opt_in,
            )


@pytest.mark.asyncio
async def test_same_version_recreation_counterexample_blocks_production_certification() -> None:
    """Document the HARD gap, not a passing assertion of concurrency safety."""
    target = receipt()
    old = metadata(target)
    recreated = {
        "created_time": NOW.isoformat(),
        "deletion_time": (NOW + timedelta(days=1)).isoformat(),
        "destroyed": False,
    }
    reads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.method == "POST":
            # Another actor deleted metadata and recreated version 1 after inspection.
            # KV-v2 destroy has no revision/CAS condition to reject that interleaving.
            recreated["destroyed"] = True
            return httpx.Response(204)
        reads += 1
        version = old if reads == 1 else recreated
        return httpx.Response(200, json={"data": {"versions": {"1": version}}})

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:58200", transport=httpx.MockTransport(handler)
    ) as client:
        result = await probe_expired_temporary_proof_destruction(
            client,
            headers={},
            receipt=target,
            now=NOW,
            grace=timedelta(seconds=1),
            isolated_acceptance=True,
        )
    assert result.outcome == "unverified"
    assert recreated["destroyed"] is True  # Detection is too late to prevent destruction.
