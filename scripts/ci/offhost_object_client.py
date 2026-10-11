#!/usr/bin/env python3
"""Authenticated HTTPS client for the recovery-lab object-store fixture."""

from __future__ import annotations

import argparse
import hashlib
import os
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.response import addinfourl


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str, ca: Path, token: str, *, data: bytes | None = None) -> addinfourl:
    context = ssl.create_default_context(cafile=str(ca))
    request = Request(
        url,
        data=data,
        method="PUT" if data is not None else "GET",
        headers={
            "Authorization": f"Bearer {token}",
            **({"X-Object-SHA256": hashlib.sha256(data).hexdigest()} if data else {}),
        },
    )
    return urlopen(request, context=context, timeout=20)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("health", "put", "get"))
    parser.add_argument("--url", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--token", default=os.environ.get("P7_OBJECT_STORE_TOKEN"))
    parser.add_argument("--key")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    if args.operation != "health" and (not args.token or not args.key or args.file is None):
        parser.error("put/get require token, --key and --file")
    url = args.url.rstrip("/")
    if args.operation == "health":
        url += "/healthz"
    else:
        url += "/v1/objects/" + args.key
    try:
        if args.operation == "put":
            assert args.file is not None and args.token is not None
            content = args.file.read_bytes()
            if not content:
                parser.error("refusing to upload an empty artifact")
            with _request(url, args.ca, args.token, data=content) as response:
                observed = response.headers.get("X-Object-SHA256")
                if observed != hashlib.sha256(content).hexdigest():
                    raise RuntimeError("storage receipt checksum differs from upload")
        else:
            with _request(url, args.ca, args.token or "") as response:
                if args.operation == "health":
                    if response.status != 204:
                        raise RuntimeError("object store health check did not return 204")
                else:
                    target = args.file
                    assert target is not None
                    digest = hashlib.sha256()
                    with target.open("wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            digest.update(chunk)
                    observed = response.headers.get("X-Object-SHA256")
                    if observed != digest.hexdigest():
                        target.unlink(missing_ok=True)
                        raise RuntimeError("download checksum differs from storage receipt")
        return 0
    except (HTTPError, URLError, OSError, RuntimeError) as exc:
        print(f"off-host transfer failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
