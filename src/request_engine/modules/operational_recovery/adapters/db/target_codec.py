from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.operational_recovery.contracts.models import RecoveryTarget


def resource_to_json(choice: ResourceChoice) -> dict[str, object]:
    assignment = choice.resource_location_assignment_id
    return {
        "requirement_id": str(choice.requirement_id),
        "resource_id": str(choice.resource_id),
        "resource_location_assignment_id": str(assignment) if assignment else None,
        "assignment_revision": choice.assignment_revision,
        "availability_revision": choice.availability_revision,
    }


def resource_from_json(raw: dict[str, object]) -> ResourceChoice:
    assignment = cast(str | None, raw.get("resource_location_assignment_id"))
    return ResourceChoice(
        requirement_id=UUID(cast(str, raw["requirement_id"])),
        resource_id=UUID(cast(str, raw["resource_id"])),
        resource_location_assignment_id=UUID(assignment) if assignment else None,
        assignment_revision=cast(int | None, raw.get("assignment_revision")),
        availability_revision=cast(int | None, raw.get("availability_revision")),
    )


def target_to_json(target: RecoveryTarget) -> dict[str, object]:
    return {
        "start_at": target.start_at.isoformat(),
        "end_at": target.end_at.isoformat(),
        "location_id": str(target.location_id) if target.location_id else None,
        "resources": [resource_to_json(choice) for choice in target.resources],
        "actionable": target.actionable,
        "blocked_reason": target.blocked_reason,
        "planned_duration_minutes": target.planned_duration_minutes,
        "amount": str(target.amount) if target.amount is not None else None,
        "currency": target.currency,
        "location_operational_revision": target.location_operational_revision,
        "configuration_fingerprint": target.configuration_fingerprint,
    }


def target_from_json(raw: dict[str, object]) -> RecoveryTarget:
    resources = cast(list[dict[str, object]], raw["resources"])
    location = cast(str | None, raw.get("location_id"))
    amount = cast(str | None, raw.get("amount"))
    return RecoveryTarget(
        start_at=datetime.fromisoformat(cast(str, raw["start_at"])),
        end_at=datetime.fromisoformat(cast(str, raw["end_at"])),
        location_id=UUID(location) if location else None,
        resources=tuple(resource_from_json(item) for item in resources),
        actionable=cast(bool, raw["actionable"]),
        blocked_reason=cast(str | None, raw.get("blocked_reason")),
        planned_duration_minutes=cast(int | None, raw.get("planned_duration_minutes")),
        amount=Decimal(amount) if amount is not None else None,
        currency=cast(str | None, raw.get("currency")),
        location_operational_revision=cast(
            int | None,
            raw.get("location_operational_revision"),
        ),
        configuration_fingerprint=cast(str | None, raw.get("configuration_fingerprint")),
    )
