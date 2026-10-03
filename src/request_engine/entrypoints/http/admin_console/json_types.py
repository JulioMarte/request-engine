"""Defensive JSON normalization for strictly-typed console code.

``json`` and untyped API payloads surface as ``Any``/unknown mappings under
pyright strict mode. These helpers turn them into explicit ``dict[str, Any]`` and
``list[Any]`` values without leaking ``Unknown`` into the type graph.
"""

from __future__ import annotations

from typing import Any, cast


def as_mapping(value: Any) -> dict[str, Any]:
    """Return a string-keyed mapping when ``value`` is dict-like, else ``{}``."""

    if isinstance(value, dict):
        source = cast("dict[object, object]", value)
        return {str(key): cast("Any", item) for key, item in source.items()}
    return {}


def as_list(value: Any) -> list[Any]:
    """Return a list when ``value`` is a list, else ``[]``."""

    if isinstance(value, list):
        return [cast("Any", item) for item in cast("list[object]", value)]
    return []


__all__ = ["as_list", "as_mapping"]
