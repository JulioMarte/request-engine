from pathlib import Path

import pytest

_HISTORICAL_ROOT = Path(__file__).parent.resolve()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify pinned release-provenance proofs independently of current-product tests."""
    for item in items:
        item_path = Path(item.path).resolve()
        if item_path.is_relative_to(_HISTORICAL_ROOT):
            item.add_marker(pytest.mark.historical)
