import argparse
import runpy
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[3] / "scripts" / "observability" / "run_with_otel.py"


def _environment(monkeypatch: pytest.MonkeyPatch, **values: str) -> dict[str, str]:
    for key in (
        "OTEL_RESOURCE_ATTRIBUTES",
        "REQUEST_ENGINE_WORKER_INSTANCE_ID",
        "REQUEST_ENGINE_ENV",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    namespace = runpy.run_path(str(LAUNCHER))
    args = argparse.Namespace(
        collector_endpoint=None,
        service_name="request-engine-worker",
        service_version="2.4.1",
    )
    return namespace["_runtime_environment"](args)


def test_launcher_merges_existing_resource_attributes_and_worker_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = _environment(
        monkeypatch,
        OTEL_RESOURCE_ATTRIBUTES="team=platform,service.version=operator-version",
        REQUEST_ENGINE_WORKER_INSTANCE_ID="worker-03",
        REQUEST_ENGINE_ENV="production",
    )

    assert env["OTEL_RESOURCE_ATTRIBUTES"] == (
        "team=platform,service.version=operator-version,service.instance.id=worker-03,"
        "deployment.environment.name=production"
    )


@pytest.mark.parametrize("worker_id", ["bad,id", "bad=value", "bad\nvalue", "x" * 129])
def test_launcher_rejects_unsafe_worker_instance_ids(
    monkeypatch: pytest.MonkeyPatch, worker_id: str
) -> None:
    with pytest.raises(ValueError, match="invalid format"):
        _environment(monkeypatch, REQUEST_ENGINE_WORKER_INSTANCE_ID=worker_id)


def test_launcher_rejects_conflicting_existing_worker_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="conflicts"):
        _environment(
            monkeypatch,
            OTEL_RESOURCE_ATTRIBUTES="service.instance.id=other-worker",
            REQUEST_ENGINE_WORKER_INSTANCE_ID="worker-03",
        )
