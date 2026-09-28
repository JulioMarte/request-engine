import pytest

from request_engine.entrypoints.http.admin_console.catalog import load_catalog
from request_engine.entrypoints.http.admin_console.forms import (
    FormSubmissionError,
    build_fields,
    parse_submission,
    render_path,
)

_OPENAPI = {
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


def test_parse_submission_requires_required_field() -> None:
    fields = build_fields(_operation())
    with pytest.raises(FormSubmissionError):
        parse_submission(fields, {"thing_id": "abc", "name": ""})


def test_render_path_substitutes_parameters() -> None:
    assert render_path("/v1/platform/things/{thing_id}", {"thing_id": "abc"}) == (
        "/v1/platform/things/abc"
    )
