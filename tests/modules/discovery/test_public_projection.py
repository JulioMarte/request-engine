from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from request_engine.modules.booking.contracts.appointments import AppointmentSlot
from request_engine.modules.discovery.api.models import DiscoveryOptionView
from request_engine.modules.discovery.application.queries.search_supply import (
    DiscoveryCandidate,
    DiscoveryOption,
)

NOW = datetime(2030, 1, 7, 14, tzinfo=UTC)


def _candidate(*, visibility: str) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        publication_id=uuid4(),
        publication_revision=1,
        mapping_id=uuid4(),
        mapping_revision=1,
        organization_id=uuid4(),
        organization_key="clinic-x",
        organization_display_name="Clinic X",
        offering_id=uuid4(),
        offering_key="cardiology",
        offering_display_name="Cardiology",
        offering_version_id=uuid4(),
        location_id=uuid4(),
        location_key="main",
        location_display_name="Clinic X Main",
        resource_id=uuid4() if visibility == "public" else None,
        provider_visibility=visibility,
        publication_start=NOW - timedelta(days=1),
        publication_end=NOW + timedelta(days=1),
        distance_meters=2100.0,
        location_address_line1="27 de Febrero 10",
        location_locality="Puerto Plata",
        location_country_code="DO",
        provider_key="dr-a" if visibility == "public" else None,
        provider_display_name="Dr. A" if visibility == "public" else None,
        provider_role_label="Cardiologist" if visibility == "public" else None,
    )


def _view(candidate: DiscoveryCandidate) -> DiscoveryOptionView:
    slot = AppointmentSlot(
        candidate.offering_version_id,
        NOW,
        NOW + timedelta(minutes=45),
        candidate.location_id,
        (),
        planned_duration_minutes=45,
        amount=Decimal("3500"),
        currency="DOP",
        location_operational_revision=1,
        configuration_fingerprint="sha256:test",
    )
    return DiscoveryOptionView.from_option(DiscoveryOption(candidate, slot), "discoopt_v1.secret")


def test_public_projection_contains_where_and_public_provider_without_internal_uuids() -> None:
    payload = _view(_candidate(visibility="public")).model_dump(mode="json")
    assert payload["location_address"]["address_line1"] == "27 de Febrero 10"
    assert payload["provider"] == {
        "resource_key": "dr-a",
        "display_name": "Dr. A",
        "role_label": "Cardiologist",
        "profile_image_ref": None,
    }
    forbidden = {
        "organization_id",
        "offering_id",
        "offering_version_id",
        "location_id",
        "resource_id",
    }
    assert forbidden.isdisjoint(payload)


def test_hidden_provider_never_crosses_public_projection() -> None:
    payload = _view(_candidate(visibility="hidden")).model_dump(mode="json")
    assert payload["provider"] is None
