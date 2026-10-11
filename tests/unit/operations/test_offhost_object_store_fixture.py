from __future__ import annotations

import hashlib
import importlib.util
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "offhost_object_store_fixture", ROOT / "scripts/ci/offhost_object_store.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.fixture
def object_store(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.ObjectStoreHandler)
    server.object_root = tmp_path  # type: ignore[attr-defined]
    server.bearer_token = b"fixture-token-at-least-32-bytes-long"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", tmp_path
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _request(url: str, *, token: str, data: bytes | None = None, digest: str = "") -> int:
    request = Request(
        url,
        data=data,
        method="PUT" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            **({"X-Object-SHA256": digest} if data is not None else {}),
        },
    )
    with urlopen(request, timeout=3) as response:
        response.read()
        return response.status


def test_authenticated_put_get_returns_matching_digest(object_store: tuple[str, Path]) -> None:
    base_url, _root = object_store
    payload = b"encrypted recovery artifact"
    digest = hashlib.sha256(payload).hexdigest()
    assert (
        _request(
            f"{base_url}/v1/objects/recovery.age",
            token="fixture-token-at-least-32-bytes-long",
            data=payload,
            digest=digest,
        )
        == 201
    )

    request = Request(
        f"{base_url}/v1/objects/recovery.age",
        headers={"Authorization": "Bearer fixture-token-at-least-32-bytes-long"},
    )
    with urlopen(request, timeout=3) as response:
        assert response.read() == payload
        assert response.headers["X-Object-SHA256"] == digest


def test_rejects_bad_authentication_digest_and_encoded_traversal(
    object_store: tuple[str, Path],
) -> None:
    base_url, root = object_store
    with pytest.raises(HTTPError) as unauthorized:
        _request(f"{base_url}/v1/objects/x", token="wrong")
    assert unauthorized.value.code == 401

    with pytest.raises(HTTPError) as mismatch:
        _request(
            f"{base_url}/v1/objects/x",
            token="fixture-token-at-least-32-bytes-long",
            data=b"payload",
            digest="0" * 64,
        )
    assert mismatch.value.code == 400
    assert not (root / "x").exists()

    with pytest.raises(HTTPError) as traversal:
        _request(
            f"{base_url}/v1/objects/%2e%2e",
            token="fixture-token-at-least-32-bytes-long",
        )
    assert traversal.value.code == 404
    assert tuple(root.iterdir()) == ()
