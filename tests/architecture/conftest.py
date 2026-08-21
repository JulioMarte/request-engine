from pathlib import Path

import pytest

_ARCHITECTURE_ROOT = Path(__file__).parent.resolve()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Classify architecture tests by evidence without encoding that class in paths."""
    for item in items:
        item_path = Path(item.path).resolve()
        if item_path.is_relative_to(_ARCHITECTURE_ROOT):
            item.add_marker(pytest.mark.fitness)
