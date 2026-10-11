#!/usr/bin/env python3
"""Small HTTPS object-store fixture for isolated recovery drills, not S3."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import re
import ssl
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import unquote, urlsplit

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_MAX_OBJECT_BYTES = 128 * 1024 * 1024


class ObjectStoreHandler(BaseHTTPRequestHandler):
    server_version = "RequestEngineLabObjectStore/1"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        # Never emit authorization headers, paths, or object names to logs.
        return

    @property
    def object_root(self) -> Path:
        return cast(Path, self.server.object_root)  # type: ignore[attr-defined]

    @property
    def bearer_token(self) -> bytes:
        return cast(bytes, self.server.bearer_token)  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "").encode("utf-8")
        expected = b"Bearer " + self.bearer_token
        return hmac.compare_digest(supplied, expected)

    def _key(self) -> str | None:
        path = urlsplit(self.path).path
        prefix = "/v1/objects/"
        if not path.startswith(prefix):
            return None
        key = unquote(path[len(prefix) :])
        if key in {".", ".."} or not _KEY.fullmatch(key):
            return None
        return key

    def do_GET(self) -> None:  # noqa: N802
        if urlsplit(self.path).path == "/healthz":
            self.send_response(204)
            self.end_headers()
            return
        if not self._authorized():
            self.send_error(401)
            return
        key = self._key()
        if key is None:
            self.send_error(404)
            return
        path = self.object_root / key
        try:
            size = path.stat().st_size
            digest = _sha256(path)
            with path.open("rb") as stream:
                self.send_response(200)
                self.send_header("Content-Length", str(size))
                self.send_header("X-Object-SHA256", digest)
                self.end_headers()
                while chunk := stream.read(1024 * 1024):
                    self.wfile.write(chunk)
        except FileNotFoundError:
            self.send_error(404)

    def do_PUT(self) -> None:  # noqa: N802
        if not self._authorized():
            self.send_error(401)
            return
        key = self._key()
        if key is None:
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self.send_error(411)
            return
        if not 0 < size <= _MAX_OBJECT_BYTES:
            self.send_error(413)
            return
        expected_digest = self.headers.get("X-Object-SHA256", "")
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=self.object_root)
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        remaining = size
        try:
            with os.fdopen(descriptor, "wb") as output:
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        self.send_error(400)
                        return
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                output.flush()
                os.fsync(output.fileno())
            actual_digest = digest.hexdigest()
            if not hmac.compare_digest(actual_digest, expected_digest):
                self.send_error(400)
                return
            os.replace(temporary, self.object_root / key)
            self.send_response(201)
            self.send_header("Content-Length", "0")
            self.send_header("X-Object-SHA256", actual_digest)
            self.end_headers()
        finally:
            temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/objects"))
    parser.add_argument("--tls-cert", type=Path, required=True)
    parser.add_argument("--tls-key", type=Path, required=True)
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8443)
    args = parser.parse_args()
    token = os.environ.get("P7_OBJECT_STORE_TOKEN", "").encode("utf-8")
    if len(token) < 32:
        parser.error("P7_OBJECT_STORE_TOKEN must contain at least 32 characters")
    args.root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.bind, args.port), ObjectStoreHandler)
    server.object_root = args.root.resolve()  # type: ignore[attr-defined]
    server.bearer_token = token  # type: ignore[attr-defined]
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(args.tls_cert, args.tls_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
