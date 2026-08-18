from pathlib import Path


def test_i13_provider_callback_ingest_cannot_mutate_business_modules_directly() -> None:
    source = Path("src/request_engine/platform/events/callbacks.py").read_text(encoding="utf-8")

    assert "request_engine.modules." not in source
    assert "record_provider_event" in source
    assert "tenant_transaction" in source
