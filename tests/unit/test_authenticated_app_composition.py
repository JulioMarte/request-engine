from inspect import signature

from request_engine.entrypoints.http.app import create_authenticated_app


def test_provider_neutral_product_constructor_accepts_subjects_not_actors() -> None:
    parameters = signature(create_authenticated_app).parameters
    assert "subject_resolver" in parameters
    assert "actor_resolver" not in parameters
