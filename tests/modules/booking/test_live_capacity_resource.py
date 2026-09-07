import pytest

from request_engine.modules.booking.adapters.db.live_capacity_resource import ProjectionResource
from request_engine.modules.booking.domain.availability import CapacityModel

pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_initial_f4_projection_accepts_only_single_exclusive_resource() -> None:
    exclusive = ProjectionResource(CapacityModel.EXCLUSIVE, 1)
    units = ProjectionResource(CapacityModel.UNITS, 2)
    multi_exclusive = ProjectionResource(CapacityModel.EXCLUSIVE, 2)

    assert exclusive.supports_sequential_projection is True
    assert units.supports_sequential_projection is False
    assert multi_exclusive.supports_sequential_projection is False
