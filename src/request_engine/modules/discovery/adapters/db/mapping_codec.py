from typing import cast
from uuid import UUID

from request_engine.modules.discovery.application.commands.mapping import (
    OfferingServiceClassificationState,
)


def state_to_json(state: OfferingServiceClassificationState) -> dict[str, object]:
    return {
        "id": str(state.id),
        "offering_id": str(state.offering_id),
        "service_classification_id": str(state.service_classification_id),
        "classification_key": state.classification_key,
        "status": state.status,
        "revision": state.revision,
    }


def state_from_json(value: dict[str, object]) -> OfferingServiceClassificationState:
    return OfferingServiceClassificationState(
        id=UUID(cast(str, value["id"])),
        offering_id=UUID(cast(str, value["offering_id"])),
        service_classification_id=UUID(cast(str, value["service_classification_id"])),
        classification_key=cast(str, value["classification_key"]),
        status=cast(str, value["status"]),
        revision=cast(int, value["revision"]),
    )
