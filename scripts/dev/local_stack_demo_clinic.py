"""DEVELOPMENT-ONLY: give the local stack's business a plausible demo clinic.

Runs the same owner operations as the console's guided setup ("Configure su
consultorio"), through public HTTP only and against loopback URLs only:
business profile, one location with opening hours, three priced services,
two doctors with weekly availability and a walk-in line. Idempotent: anything
that already exists by key is left as it is.

    uv run python scripts/dev/local_stack_demo_clinic.py --project request-engine-dev
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[2]
WEEKDAYS = range(5)  # Monday..Friday
SERVICES = (
    ("consulta-general", "Consulta general", 30, "1500"),
    ("consulta-pediatrica", "Consulta pediátrica", 30, "1800"),
    ("control-prenatal", "Control prenatal", 45, "2200"),
)
DOCTORS = (
    ("dra-ana-perez", "Dra. Ana Pérez", ("consulta-general", "control-prenatal")),
    ("dr-luis-rosario", "Dr. Luis Rosario", ("consulta-general", "consulta-pediatrica")),
)


def _loopback(url: str) -> str:
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1"}:
        raise SystemExit(f"refusing non-loopback URL {url}")
    return url.rstrip("/")


class Owner:
    def __init__(self, runtime: str, control: str, login: str, password: str, org: str) -> None:
        session = httpx.post(
            f"{control}/auth/native/sessions",
            json={"login_handle": login, "password": password},
            timeout=30,
        )
        session.raise_for_status()
        self._client = httpx.Client(
            base_url=runtime,
            timeout=30,
            headers={
                "Authorization": f"Bearer {session.json()['access_token']}",
                "X-RE-Organization-ID": org,
            },
        )

    def get(self, path: str, **params: Any) -> Any:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def write(self, method: str, path: str, body: dict[str, Any], key: str) -> Any:
        response = self._client.request(
            method, path, json=body, headers={"Idempotency-Key": f"demo-clinic:{key}"}
        )
        if response.status_code >= 400:
            raise SystemExit(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else {}


def _items(payload: Any) -> list[dict[str, Any]]:
    rows = cast(list[dict[str, Any]], payload if isinstance(payload, list) else payload["items"])
    return [dict(row) for row in rows]


def _party(owner: Owner, scope: str) -> str:
    after: str | None = None
    while True:
        page = owner.get("/v1/me/authority", **({"after": after} if after else {}))
        for item in page.get("representations", []):
            if item.get("scope_key") == scope:
                return str(item["represented_party_id"])
        after = page.get("next_after")
        if not after:
            raise SystemExit(f"owner has no {scope} representation")


def _windows(start: str, end: str) -> list[dict[str, Any]]:
    return [{"weekday": day, "local_start": start, "local_end": end} for day in WEEKDAYS]


def seed(owner: Owner) -> None:
    party = _party(owner, "operations.manage_profile")
    supply_party = _party(owner, "operations.manage_supply")
    terms_party = _party(owner, "operations.manage_terms")
    owner.write(
        "PATCH",
        "/v1/operations/organization/profile",
        {
            "authority_party_id": party,
            "legal_name": "Centro Médico Duarte SRL",
            "default_timezone": "America/Santo_Domingo",
            "default_locale": "es-DO",
            "default_currency": "DOP",
        },
        "profile",
    )

    locations = _items(
        owner.get("/v1/catalog/locations/configuration", authority_party_id=party, limit=100)
    )
    location = next((loc for loc in locations if loc.get("location_key") == "sede-gazcue"), None)
    if location is None:
        created = owner.write(
            "POST",
            "/v1/operations/locations",
            {
                "authority_party_id": party,
                "location_key": "sede-gazcue",
                "display_name": "Sede Gazcue",
                "timezone": "America/Santo_Domingo",
                "address_line1": "Av. Independencia 123",
                "locality": "Santo Domingo",
                "administrative_area": "Distrito Nacional",
                "country_code": "DO",
            },
            "location",
        )
        owner.write(
            "PUT",
            f"/v1/operations/locations/{created['location_id']}/hours",
            {
                "authority_party_id": party,
                "expected_operational_revision": created["operational_revision"],
                "windows": _windows("08:00", "17:00"),
            },
            "location-hours",
        )
        location_id = str(created["location_id"])
    else:
        location_id = str(location["location_id"])

    offerings = _items(
        owner.get("/v1/catalog/offerings/configuration", authority_party_id=party, limit=100)
    )
    capability_ids: dict[str, str] = {}
    capabilities = _items(owner.get("/v1/catalog/resource-capabilities", limit=200))
    for key, name, minutes, price in SERVICES:
        capability_key = f"provides-{key}"
        capability = next(
            (c for c in capabilities if c.get("capability_key") == capability_key), None
        )
        if capability is None:
            capability = owner.write(
                "POST",
                "/v1/catalog/resource-capabilities",
                {
                    "authority_party_id": party,
                    "capability_key": capability_key,
                    "display_name": f"Ofrece {name}",
                },
                f"capability-{key}",
            )
        capability_ids[key] = str(capability["capability_id"])
        if any(o.get("offering_key") == key for o in offerings):
            continue
        offering = owner.write(
            "POST",
            "/v1/catalog/offerings",
            {
                "authority_party_id": party,
                "offering_key": key,
                "display_name": name,
                "duration_minutes": minutes,
                "slot_step_minutes": minutes,
                "requirements": [{"capability_id": capability_ids[key], "quantity": 1}],
            },
            f"offering-{key}",
        )
        owner.write(
            "PUT",
            f"/v1/operations/offering-versions/{offering['offering_version_id']}/booking-terms",
            {"authority_party_id": terms_party, "amount": price, "currency": "DOP"},
            f"terms-{key}",
        )

    resources = _items(owner.get("/v1/booking/resources", authority_party_id=supply_party))
    for key, name, services in DOCTORS:
        if any(r.get("resource_key") == key for r in resources):
            continue
        owner.write(
            "POST",
            "/v1/booking/resources",
            {
                "authority_party_id": supply_party,
                "location_id": location_id,
                "resource_key": key,
                "display_name": name,
                "capacity_model": "exclusive",
                "capability_ids": [capability_ids[s] for s in services],
                "weekly_availability": _windows("08:00", "17:00"),
            },
            f"resource-{key}",
        )

    queues = _items(owner.get("/v1/queues/configuration", authority_party_id=supply_party))
    if not any(q.get("queue_key") == "fila-de-llegada" for q in queues):
        owner.write(
            "POST",
            "/v1/queues",
            {
                "authority_party_id": supply_party,
                "location_id": location_id,
                "queue_key": "fila-de-llegada",
                "display_name": "Fila de llegada",
            },
            f"queue-{uuid.uuid5(uuid.NAMESPACE_URL, location_id)}",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed a development demo clinic.")
    parser.add_argument("--project", default="request-engine-dev")
    parser.add_argument("--api-url", default="http://localhost:58100")
    parser.add_argument("--control-url", default="http://localhost:58101")
    args = parser.parse_args()
    credentials = json.loads(
        (ROOT / ".local-stack" / args.project / "credentials.json").read_text(encoding="utf-8")
    )
    owner = Owner(
        _loopback(args.api_url),
        _loopback(args.control_url),
        credentials["business_owner"]["login"],
        credentials["business_owner"]["password"],
        credentials["organization_id"],
    )
    seed(owner)
    print("demo clinic ready: Sede Gazcue, 3 services, 2 doctors, Fila de llegada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
