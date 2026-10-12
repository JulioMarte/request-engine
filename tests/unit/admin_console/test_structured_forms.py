"""Nested visual inputs preserve typed owner payloads and omit untouched settings."""

from pathlib import Path
from typing import Any

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.forms import (
    FormSubmissionError,
    build_fields,
    parse_submission,
)
from request_engine.entrypoints.http.admin_console.inputs import build_inputs


def _operation():  # type: ignore[no-untyped-def]
    document: dict[str, Any] = {
        "paths": {
            "/settings": {
                "post": {
                    "operationId": "save",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["hours"],
                                    "properties": {
                                        "hours": {
                                            "type": "array",
                                            "items": {"$ref": "#/components/schemas/Hours"},
                                        },
                                        "profile": {
                                            "anyOf": [
                                                {"$ref": "#/components/schemas/Profile"},
                                                {"type": "null"},
                                            ]
                                        },
                                        "expected_revision": {"type": "integer"},
                                        "open_config": {"type": "object"},
                                    },
                                }
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "Hours": {
                    "type": "object",
                    "required": ["day", "enabled"],
                    "properties": {
                        "day": {"type": "integer"},
                        "enabled": {"type": "boolean"},
                        "label": {"type": "string"},
                    },
                },
                "Profile": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "channels": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["email", "sms"]},
                        },
                    },
                },
            }
        },
    }
    return load_catalog(document).by_id()["save"]


def _render(inputs: list[dict[str, Any]]) -> str:
    path = Path(__file__).parents[3] / "src/request_engine/entrypoints/http/admin_console/templates"
    environment = Environment(loader=FileSystemLoader(path), autoescape=select_autoescape())
    return environment.from_string(
        '{% import "partials/inputs.html" as ui %}{{ ui.render(inputs) }}'
    ).render(inputs=inputs)


def test_nested_refs_and_nullable_objects_render_visual_controls() -> None:
    inputs = build_inputs(_operation(), values={"hours": '[{"day": 1, "enabled": false}]'})
    html = _render(inputs)
    assert 'name="hours[0].day" value="1"' in html
    assert 'name="hours[0].enabled"' in html
    assert 'value="false" selected' in html
    assert 'name="profile.name"' in html
    assert 'name="profile.channels[__INDEX_1__]"' in html
    assert 'name="hours" rows=' not in html
    assert 'name="open_config" rows=' in html
    assert "data-array-add" in html


def test_visual_controls_reconstruct_typed_arrays_with_removed_rows_and_explicit_false() -> None:
    form = {
        "__structured__hours": "true",
        "__structured__hours[0]": "true",
        "hours[0].day": "1",
        "hours[0].enabled": "false",
        "__structured__hours[4]": "true",
        "hours[4].day": "3",
        "hours[4].enabled": "true",
        "__structured__profile": "true",
        "__include__profile": "true",
        "profile.name": "Clinic",
        "__structured__profile.channels": "true",
        "__include__profile.channels": "true",
        "profile.channels[2]": "email",
        "profile.channels[7]": "sms",
        "profile.unknown": "ignored",
    }
    result = parse_submission(build_fields(_operation()), form)
    assert result.body == {
        "hours": [{"day": 1, "enabled": False}, {"day": 3, "enabled": True}],
        "profile": {"name": "Clinic", "channels": ["email", "sms"]},
    }


def test_empty_array_and_unselected_optional_group_are_distinct() -> None:
    result = parse_submission(
        build_fields(_operation()),
        {
            "__structured__hours": "true",
            "__structured__profile": "true",
            "profile.name": "",
        },
    )
    assert result.body == {"hours": []}


def test_missing_required_nested_control_fails_before_upstream() -> None:
    with pytest.raises(FormSubmissionError, match="Enabled is required"):
        parse_submission(
            build_fields(_operation()),
            {
                "__structured__hours": "true",
                "__structured__hours[0]": "true",
                "hours[0].day": "2",
            },
        )


def test_too_many_array_entries_fail_before_upstream() -> None:
    form = {"__structured__hours": "true"}
    form.update({f"hours[{index}].day": "1" for index in range(101)})
    with pytest.raises(FormSubmissionError, match="too many entries"):
        parse_submission(build_fields(_operation()), form)


def test_revision_is_hidden_only_when_explicitly_loaded_and_never_invented() -> None:
    absent = _render(build_inputs(_operation()))
    assert 'type="number" step="1" name="expected_revision" value=""' in absent
    unverified = _render(build_inputs(_operation(), values={"expected_revision": "900"}))
    assert 'type="number" step="1" name="expected_revision" value="900"' in unverified
    assert "Current version loaded" not in unverified
    loaded = _render(
        build_inputs(
            _operation(),
            values={"expected_revision": "12"},
            loaded_revisions=("expected_revision",),
        )
    )
    assert 'type="hidden" name="expected_revision" value="12"' in loaded
    assert "Current version loaded" in loaded


def test_foreign_label_markup_is_escaped_and_empty_choices_do_not_become_id_input() -> None:
    inputs = build_inputs(_operation())
    field = inputs[2]
    field["enum_options"] = [{"value": "12", "label": '<img src=x onerror="alert(1)">'}]
    html = _render([field])
    assert "&lt;img" in html
    assert "<img" not in html
    field["enum_options"] = []
    assert '<select name="expected_revision"' in _render([field])


def test_recursive_schema_is_bounded_and_keeps_open_shape_advanced() -> None:
    operation = load_catalog(
        {
            "paths": {
                "/x": {
                    "post": {
                        "operationId": "x",
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Node"}
                                },
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "Node": {
                        "type": "object",
                        "properties": {
                            "child": {"$ref": "#/components/schemas/Node"},
                        },
                    }
                }
            },
        }
    ).by_id()["x"]
    assert len(build_fields(operation)) == 1


@pytest.mark.parametrize("field,value", [("hours", "{}"), ("open_config", "[]")])
def test_advanced_json_still_requires_declared_container_shape(field: str, value: str) -> None:
    with pytest.raises(FormSubmissionError, match="must be an"):
        parse_submission(build_fields(_operation()), {"hours": "[]", field: value})


def test_loaded_unknown_object_keys_remain_in_advanced_payload_instead_of_disappearing() -> None:
    inputs = build_inputs(
        _operation(),
        values={
            "hours": "[]",
            "profile": '{"name":"Clinic","future_setting":{"active":false}}',
        },
    )
    profile = inputs[1]
    assert profile["structured"] is False
    assert "future_setting" in _render([profile])
    result = parse_submission(
        build_fields(_operation()),
        {
            "hours": "[]",
            "profile": profile["value"],
        },
    )
    assert result.body == {
        "hours": [],
        "profile": {
            "name": "Clinic",
            "future_setting": {"active": False},
        },
    }


def test_nullable_structured_group_preserves_loaded_null_and_can_clear_without_json() -> None:
    inputs = build_inputs(_operation(), values={"hours": "[]", "profile": "null"})
    profile = inputs[1]
    assert profile["structured"] is True
    assert profile["null_value"] is True
    html = _render([profile])
    assert 'name="__mode__profile"' in html
    assert 'value="null" selected' in html
    result = parse_submission(
        build_fields(_operation()),
        {
            "__structured__hours": "true",
            "__structured__profile": "true",
            "__include__profile": "true",
            "__mode__profile": "null",
        },
    )
    assert result.body == {"hours": [], "profile": None}


def test_required_choice_never_selects_first_account_without_user_choice() -> None:
    inputs = build_inputs(_operation())
    field = inputs[2]
    field["required"] = True
    field["choices"] = [{"value": "12", "label": "Administrator"}]
    html = _render([field])
    assert '<option value="" selected>Choose Expected Revision</option>' in html
    assert '<option value="12">Administrator</option>' in html


def test_structured_nested_empty_values_and_null_scalars_survive_unchanged() -> None:
    from dataclasses import replace

    operation = replace(
        _operation(),
        body_schema={
            "type": "object",
            "required": ["settings"],
            "properties": {
                "settings": {
                    "type": "object",
                    "properties": {
                        "active": {"type": "boolean"},
                        "names": {"type": "array", "items": {"type": "string"}},
                        "details": {"type": "object", "properties": {"label": {"type": "string"}}},
                        "contact": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    },
                }
            },
        },
    )
    inputs = build_inputs(
        operation,
        values={
            "settings": '{"active":false,"names":[],"details":{},"contact":null}',
        },
    )
    children = inputs[0]["children"]
    assert children[1]["included"] and children[1]["rows"] == []
    assert children[2]["included"]
    assert children[3]["preserve_null"]
    result = parse_submission(
        build_fields(operation),
        {
            "__structured__settings": "true",
            "settings.active": "false",
            "__structured__settings.names": "true",
            "__include__settings.names": "true",
            "__structured__settings.details": "true",
            "__include__settings.details": "true",
            "settings.details.label": "",
            "__null__settings.contact": "true",
            "settings.contact": "",
        },
    )
    assert result.body == {
        "settings": {"active": False, "names": [], "details": {}, "contact": None}
    }


def test_required_nullable_group_accepts_clear_value_without_required_children() -> None:
    from dataclasses import replace

    operation = _operation()
    assert operation.body_schema is not None
    operation = replace(
        operation, body_schema={**operation.body_schema, "required": ["hours", "profile"]}
    )
    html = _render(build_inputs(operation, values={"profile": "null"}))
    assert 'name="__include__profile"' not in html
    result = parse_submission(
        build_fields(operation),
        {
            "__structured__hours": "true",
            "__structured__profile": "true",
            "__mode__profile": "null",
        },
    )
    assert result.body == {"hours": [], "profile": None}


@pytest.mark.parametrize(
    "value,native", [("09:00:00.123", True), ("09:00:00.123456", False), ("09:00:00+03:00", False)]
)
def test_time_controls_preserve_existing_precision_and_offsets(value: str, native: bool) -> None:
    from dataclasses import replace

    operation = replace(
        _operation(),
        body_schema={
            "type": "object",
            "required": ["start"],
            "properties": {"start": {"type": "string", "format": "time"}},
        },
    )
    html = _render(build_inputs(operation, values={"start": value}))
    expected = 'type="time" step="any"' if native else 'type="text"'
    assert f'{expected} name="start" value="{value}"' in html
    result = parse_submission(build_fields(operation), {"start": value})
    assert result.body == {"start": value}


def test_hours_use_named_weekdays_and_date_time_controls_without_losing_offsets() -> None:
    from dataclasses import replace

    operation = replace(
        _operation(),
        body_schema={
            "type": "object",
            "properties": {
                "hours": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "weekday": {"type": "integer", "minimum": 0, "maximum": 6},
                            "start_time": {"type": "string", "format": "time"},
                            "date": {"type": "string", "format": "date"},
                            "at": {"type": "string", "format": "date-time"},
                        },
                    },
                }
            },
        },
    )
    html = _render(
        build_inputs(
            operation,
            values={
                "hours": (
                    '[{"weekday":0,"start_time":"09:00:00","date":"2026-10-12",'
                    '"at":"2026-10-12T09:00:00-04:00"}]'
                ),
            },
        )
    )
    assert '<option value="0" selected>Monday</option>' in html
    assert '<option value="6">Sunday</option>' in html
    assert 'type="time" step="any" name="hours[0].start_time" value="09:00:00"' in html
    assert 'type="date" name="hours[0].date" value="2026-10-12"' in html
    assert 'type="text" name="hours[0].at" value="2026-10-12T09:00:00-04:00"' in html
    result = parse_submission(
        build_fields(operation),
        {
            "__structured__hours": "true",
            "__include__hours": "true",
            "__structured__hours[0]": "true",
            "hours[0].weekday": "0",
            "hours[0].start_time": "09:00:00",
            "hours[0].date": "2026-10-12",
            "hours[0].at": "2026-10-12T09:00:00-04:00",
        },
    )
    assert result.body == {
        "hours": [
            {
                "weekday": 0,
                "start_time": "09:00:00",
                "date": "2026-10-12",
                "at": "2026-10-12T09:00:00-04:00",
            }
        ]
    }
