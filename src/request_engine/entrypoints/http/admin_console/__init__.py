"""Private operator admin console.

The console is a separate HTTP entrypoint that projects the platform control-plane
API. It owns no business logic and never talks to PostgreSQL, OpenBao or provider
SDKs directly: every action is an HTTP call to the control plane, which keeps the
existing capability/step-up authority as the single execution path.
"""

from request_engine.entrypoints.http.admin_console.app import (
    create_admin_console_app,
)

__all__ = ["create_admin_console_app"]
