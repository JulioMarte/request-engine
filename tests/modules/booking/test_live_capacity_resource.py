import pytest

from request_engine.modules.booking.adapters.db.live_capacity_resource import ProjectionResource
from request_engine.modules.booking.domain.availability import CapacityModel

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_initial_f4_projection_accepts_only_single_exclusive_resource() -> None:
    exclusive = ProjectionResource(None, CapacityModel.EXCLUSIVE, 1, "UTC")
    units = ProjectionResource(None, CapacityModel.UNITS, 2, "UTC")
    multi_exclusive = ProjectionResource(None, CapacityModel.EXCLUSIVE, 2, "UTC")

    assert exclusive.supports_sequential_projection is True
    assert units.supports_sequential_projection is False
    assert multi_exclusive.supports_sequential_projection is False
