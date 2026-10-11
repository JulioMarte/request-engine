from dataclasses import replace
from typing import Any

import pytest

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.forms import (
    FormSubmissionError,
    build_fields,
    parse_submission,
    render_path,
)

_OPENAPI: dict[str, Any] = {
    "paths": {
        "/v1/platform/things/{thing_id}": {
            "post": {
                "operationId": "thing_update",
                "parameters": [
                    {
                        "name": "thing_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "count": {"type": "integer"},
                                    "active": {"type": "boolean"},
                                    "meta": {"type": "object"},
                                },
                            }
                        }
                    }
                },
            }
        }
    }
}


def _operation():  # type: ignore[no-untyped-def]
    return load_catalog(_OPENAPI).by_id()["thing_update"]


def test_build_fields_flattens_path_and_body() -> None:
    fields = build_fields(_operation())
    names = {field.name for field in fields}
    assert names == {"thing_id", "name", "count", "active", "meta"}
    required = {field.name for field in fields if field.required}
    assert required == {"thing_id", "name"}


def test_parse_submission_coerces_types() -> None:
    fields = build_fields(_operation())
    submission = parse_submission(
        fields,
        {"thing_id": "abc", "name": "widget", "count": "7", "active": "true", "meta": '{"k": 1}'},
    )
    assert submission.path_params == {"thing_id": "abc"}
    assert submission.body == {"name": "widget", "count": 7, "active": True, "meta": {"k": 1}}


def test_parse_submission_omits_empty_optional() -> None:
    fields = build_fields(_operation())
    submission = parse_submission(fields, {"thing_id": "abc", "name": "widget", "count": ""})
    assert submission.body == {"name": "widget"}


def test_parse_submission_rejects_bad_integer() -> None:
    fields = build_fields(_operation())
    with pytest.raises(FormSubmissionError):
        parse_submission(fields, {"thing_id": "abc", "name": "widget", "count": "not-a-number"})


@pytest.mark.parametrize("raw", ["typo", "2", "maybe"])
def test_boolean_typo_does_not_silently_disable_setting(raw: str) -> None:
    with pytest.raises(FormSubmissionError, match="must be a boolean"):
        parse_submission(
            build_fields(_operation()), {"thing_id": "abc", "name": "x", "active": raw}
        )


@pytest.mark.parametrize("raw", ["false", "0", "off", "no"])
def test_explicit_false_setting_remains_supported(raw: str) -> None:
    result = parse_submission(
        build_fields(_operation()), {"thing_id": "abc", "name": "x", "active": raw}
    )
    assert result.body == {"name": "x", "active": False}


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-inf", "1e999"])
def test_nonfinite_numbers_are_form_errors_not_transport_failures(raw: str) -> None:
    count = next(field for field in build_fields(_operation()) if field.name == "count")
    with pytest.raises(FormSubmissionError, match="finite number"):
        parse_submission((replace(count, kind="number"),), {"count": raw})


@pytest.mark.parametrize("raw", ['{"nested": [NaN]}', "[Infinity]", '{"value": 1e999}'])
def test_nonfinite_nested_json_is_rejected(raw: str) -> None:
    with pytest.raises(FormSubmissionError, match="valid JSON"):
        parse_submission(build_fields(_operation()), {"thing_id": "abc", "name": "x", "meta": raw})


def test_parse_submission_requires_required_field() -> None:
    fields = build_fields(_operation())
    with pytest.raises(FormSubmissionError):
        parse_submission(fields, {"thing_id": "abc", "name": ""})


def test_render_path_substitutes_parameters() -> None:
    assert render_path("/v1/platform/things/{thing_id}", {"thing_id": "abc"}) == (
        "/v1/platform/things/abc"
    )


@pytest.mark.parametrize("value", [".", "..", "../other", "a/b", "a\\b"])
def test_render_path_rejects_segment_traversal(value: str) -> None:
    with pytest.raises(FormSubmissionError, match="single resource segment"):
        render_path("/v1/things/{thing_id}:run", {"thing_id": value})


def test_render_path_encodes_query_fragment_and_literal_percent_without_changing_method() -> None:
    assert render_path("/v1/things/{thing_id}:run", {"thing_id": "name?x=1#frag%2F"}) == (
        "/v1/things/name%3Fx%3D1%23frag%252F:run"
    )


def test_explicit_empty_nullable_field_is_null_not_omitted_or_literal_text() -> None:
    from copy import deepcopy

    schema = deepcopy(_OPENAPI)
    body = schema["paths"]["/v1/platform/things/{thing_id}"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]
    body["properties"]["name"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    fields = build_fields(load_catalog(schema).by_id()["thing_update"])
    assert parse_submission(fields, {"thing_id": "abc", "name": ""}).body == {"name": None}
    assert parse_submission(fields, {"thing_id": "abc", "name": "null"}).body == {"name": "null"}
    with pytest.raises(FormSubmissionError):
        parse_submission(fields, {"thing_id": "abc"})
