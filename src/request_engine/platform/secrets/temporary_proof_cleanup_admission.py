"""Protected operator evidence binding; configuration is not proof of provider ACLs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class TemporaryCleanupAdmission:
    """Attested deployment, never inferred from a loopback URL or successful staging.

    The artifact and its three bound files are protected operator inputs, not API
    arguments. Operators must audit effective provider policies, revoke janitor
    credentials and stop workers BEFORE restore/recreation; rotating the fence
    file invalidates existing workers. This cannot contain a root operator who
    bypasses the stop/revoke protocol. Evidence freshness is bounded to one day.
    """

    admission_id: UUID
    backend_id: UUID
    provider_origin: str
    mount: str
    grace_seconds: int
    certified_at: datetime
    valid_until: datetime
    artifact: Path
    artifact_digest: str
    bound_files: tuple[tuple[Path, str], ...]

    @classmethod
    def load(cls, artifact: Path) -> TemporaryCleanupAdmission:
        if artifact.stat().st_size > 65536:
            raise ValueError("cleanup admission artifact is oversized")
        raw = artifact.read_bytes()
        decoded: object = json.loads(raw)
        names = {
            "schema",
            "admission_id",
            "backend_id",
            "provider_origin",
            "mount",
            "namespace",
            "grace_seconds",
            "certified_at",
            "valid_until",
            "policy_bundle_path",
            "policy_bundle_sha256",
            "restore_fence_path",
            "restore_fence_sha256",
            "acceptance_evidence_path",
            "acceptance_evidence_sha256",
        }
        if not isinstance(decoded, dict):
            raise ValueError("cleanup admission fields are invalid")
        fields = cast(dict[str, object], decoded)
        if set(fields) != names:
            raise ValueError("cleanup admission fields are invalid")
        if any(not isinstance(fields[key], str) for key in names - {"grace_seconds"}):
            raise ValueError("cleanup admission field types are invalid")
        value = {key: cast(str, fields[key]) for key in names - {"grace_seconds"}}
        if value["schema"] != "temporary-proof-cleanup-admission/v1" or value["namespace"] != (
            "request-engine/identity-recovery"
        ):
            raise ValueError("cleanup admission namespace is unsupported")
        grace = fields["grace_seconds"]
        if type(grace) is not int or not 1 <= grace <= 604800:
            raise ValueError("cleanup admission grace is invalid")
        origin = urlsplit(value["provider_origin"])
        if (
            origin.scheme not in ("http", "https")
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in ("", "/")
            or origin.query
            or origin.fragment
            or (
                origin.scheme == "http" and origin.hostname not in ("localhost", "127.0.0.1", "::1")
            )
        ):
            raise ValueError("cleanup admission provider origin is invalid")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["mount"]) is None:
            raise ValueError("cleanup admission mount is invalid")
        admission_id, backend_id = UUID(value["admission_id"]), UUID(value["backend_id"])
        if not admission_id.int or not backend_id.int:
            raise ValueError("cleanup admission identities are invalid")
        certified = datetime.fromisoformat(value["certified_at"])
        until = datetime.fromisoformat(value["valid_until"])
        if (
            certified.tzinfo is None
            or until.tzinfo is None
            or not (timedelta(0) < until - certified <= timedelta(days=1))
        ):
            raise ValueError("cleanup admission validity window is invalid")
        bindings: list[tuple[Path, str]] = []
        for stem in ("policy_bundle", "restore_fence", "acceptance_evidence"):
            expected = value[f"{stem}_sha256"]
            if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
                raise ValueError("cleanup admission fingerprint is invalid")
            path = artifact.parent / value[f"{stem}_path"]
            if not path.is_file():
                raise ValueError("cleanup admission evidence is unavailable")
            bindings.append((path, expected))
        return cls(
            admission_id,
            backend_id,
            value["provider_origin"].rstrip("/"),
            value["mount"],
            grace,
            certified,
            until,
            artifact,
            hashlib.sha256(raw).hexdigest(),
            tuple(bindings),
        )

    def assert_current(self, *, now: datetime, provider_origin: str, outbound_fenced: bool) -> None:
        if (
            outbound_fenced
            or now.tzinfo is None
            or not self.certified_at <= now < self.valid_until
            or provider_origin.rstrip("/") != self.provider_origin
            or _fingerprint(self.artifact) != self.artifact_digest
            or any(_fingerprint(path) != expected for path, expected in self.bound_files)
        ):
            raise ValueError("temporary proof cleanup deployment is not admitted")
