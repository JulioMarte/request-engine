from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def private_session_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "REQUEST_ENGINE_ADMIN_CONSOLE_SESSION_STORE_DIRECTORY", str(tmp_path / "sessions")
    )
