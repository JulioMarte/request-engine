from __future__ import annotations

import base64
import hashlib
import zlib
from pathlib import Path

PAYLOAD_DIRECTORY = Path(__file__).resolve().parent / "sql" / "v3_initial"
PAYLOAD_PARTS = (
    "0001_initial.payload.01.b85",
    "0001_initial.payload.02.b85",
    "0001_initial.payload.03.b85",
)
EXPECTED_SQL_BYTES = 364122
EXPECTED_SQL_SHA256 = "502c98fcce5b5480a3e8f34804ce3a61495e679811a3ac6d0be4872107c34c88"


def load_v3_initial_sql() -> str:
    encoded = "".join(
        (PAYLOAD_DIRECTORY / filename).read_text(encoding="ascii").strip()
        for filename in PAYLOAD_PARTS
    )
    try:
        compressed = base64.b85decode(encoded.encode("ascii"))
        payload = zlib.decompress(compressed)
    except (ValueError, zlib.error) as exc:
        raise RuntimeError("V3 0001_initial payload cannot be decoded") from exc

    if len(payload) != EXPECTED_SQL_BYTES:
        raise RuntimeError(
            "V3 0001_initial payload byte length does not match the reviewed baseline"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SQL_SHA256:
        raise RuntimeError("V3 0001_initial payload checksum does not match the reviewed baseline")

    text = payload.decode("utf-8")
    if any(line.startswith("\\") for line in text.splitlines()):
        raise RuntimeError("V3 0001_initial payload contains a psql meta-command")
    return text
