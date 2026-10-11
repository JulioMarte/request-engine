"""Composition entrypoint for the private admin console process.

Loads the console settings from the environment and returns the ASGI app so the
process can be started with a uvicorn factory. The console is a separate private
listener; it never shares the control-plane trust boundary directly.
"""

from fastapi import FastAPI

from request_engine.entrypoints.http.admin_console import create_admin_console_app
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings


def create_app() -> FastAPI:
    """Build the admin console app from ``REQUEST_ENGINE_ADMIN_CONSOLE_*`` settings."""

    return create_admin_console_app(AdminConsoleSettings.model_validate({}))


__all__ = ["create_app"]
