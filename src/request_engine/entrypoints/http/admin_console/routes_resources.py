"""Task-oriented resource workspaces over the control-plane operations.

Read (list/get) and act (semantic commands) are wired together here: a resource
page loads its state through the owning read operation and its action forms are
pre-filled with the revisions/binding ids those commands require, so an operator
never has to copy concurrency preconditions by hand (docs/15 §11). Every action
still executes through the shared ``execution.execute_operation`` path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.execution import (
    ExecutionOutcome,
    execute_operation,
    local_error,
)
from request_engine.entrypoints.http.admin_console.inputs import (
    build_inputs,
    scalar_columns,
    summarize_payload,
)
from request_engine.entrypoints.http.admin_console.json_types import as_mapping
from request_engine.entrypoints.http.admin_console.resources import (
    CONFIGURATION_OPERATION_IDS,
    DEPLOYMENT_OPERATION_IDS,
    OWNER_OPERATION_IDS,
    PROVISIONING_OPERATION_IDS,
    RESOURCE_SPECS,
    SECRET_OPERATION_IDS,
    WORKSPACE_SPECS,
    MissingOperation,
    item_reference,
    list_items,
    next_cursor,
    pagination_params,
    prefill_values,
    resolve_operation,
    spec_by_key,
    workspace_by_key,
)
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_CONFIG_ACTIONS = {
    "validate": CONFIGURATION_OPERATION_IDS["validate"],
    "activate": CONFIGURATION_OPERATION_IDS["activate"],
    "disable": CONFIGURATION_OPERATION_IDS["disable"],
    "test": CONFIGURATION_OPERATION_IDS["provider_test"],
}
_SECRET_ACTIONS = {
    "create": (SECRET_OPERATION_IDS["create"], ("value",)),
    "rotate": (SECRET_OPERATION_IDS["rotate"], ("value",)),
    "revoke": (SECRET_OPERATION_IDS["revoke"], ()),
    "keyring-create": (SECRET_OPERATION_IDS["keyring_create"], ()),
    "keyring-rotate": (SECRET_OPERATION_IDS["keyring_rotate"], ()),
}
_DEPLOYMENT_ACTIONS = {
    "configure": DEPLOYMENT_OPERATION_IDS["configure"],
    "reconcile": DEPLOYMENT_OPERATION_IDS["reconcile"],
}
_OWNER_ACTIONS = {
    "invite": OWNER_OPERATION_IDS["invite"],
    "revoke-invitation": OWNER_OPERATION_IDS["revoke_invitation"],
    "activate-invitation": OWNER_OPERATION_IDS["activate_invitation"],
    "suspend": OWNER_OPERATION_IDS["suspend"],
    "reactivate": OWNER_OPERATION_IDS["reactivate"],
    "revoke": OWNER_OPERATION_IDS["revoke"],
}
_PROVISIONING_ACTIONS = {
    "organization": PROVISIONING_OPERATION_IDS["organization_create"],
    "recovery-operator": PROVISIONING_OPERATION_IDS["recovery_operator_create"],
}


def install_resource_routes(app: FastAPI, state: AdminConsoleState) -> None:
    def _session(request: Request):  # noqa: ANN202 - small closure helper
        return state.session(request)

    def _bearer(request: Request) -> str | None:
        session = _session(request)
        return session.access_token if session is not None else None

    async def _catalog():  # noqa: ANN202
        return await state.catalog()

    def _result_response(request: Request, outcome: ExecutionOutcome, *, form_id: str) -> Response:
        return state.templates.TemplateResponse(
            request,
            "partials/result.html",
            state.context(request, result=outcome.to_view(), form_id=form_id),
        )

    def _drift(request: Request, operation_id: str) -> Response:
        outcome = local_error(
            503, "operation_unavailable", f"control plane no longer exposes {operation_id}"
        )
        return _result_response(request, outcome, form_id="drift")

    async def _run_action(request: Request, operation_id: str, *, form_id: str) -> Response:
        session = _session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        try:
            operation = resolve_operation(await _catalog(), operation_id)
        except MissingOperation:
            return _drift(request, operation_id)
        assert operation is not None
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return _result_response(
                request,
                local_error(403, "csrf_failed", "CSRF token missing or invalid"),
                form_id=form_id,
            )
        outcome = await execute_operation(
            state, operation, bearer=session.access_token, form=values
        )
        return _result_response(request, outcome, form_id=form_id)

    def _action_context(
        request: Request,
        operation: AdminOperation | None,
        *,
        action_url: str,
        form_id: str,
        values: Mapping[str, str] | None = None,
        secret_fields: tuple[str, ...] = (),
        submit_label: str = "Run",
        danger: bool = False,
        confirm: str = "",
        description: str = "",
    ) -> dict[str, Any]:
        return state.context(
            request,
            operation=operation,
            inputs=build_inputs(operation, values=values, secret_fields=secret_fields)
            if operation is not None
            else [],
            action_url=action_url,
            form_id=form_id,
            submit_label=submit_label,
            danger=danger,
            confirm=confirm,
            action_description=description,
        )

    # ---------------------------------------------------------------- index

    async def resources_index(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        groups: dict[str, list[dict[str, str]]] = {}
        for spec in RESOURCE_SPECS:
            groups.setdefault(spec.owner, []).append(
                {"key": spec.key, "title": spec.title, "summary": spec.summary}
            )
        for workspace in WORKSPACE_SPECS:
            groups.setdefault(workspace.owner, []).append(
                {"key": workspace.key, "title": workspace.title, "summary": workspace.summary}
            )
        return state.templates.TemplateResponse(
            request, "resources/index.html", state.context(request, groups=groups)
        )

    # ------------------------------------------------------- simple resources

    async def resource_list(request: Request, resource_key: str) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        spec = spec_by_key(resource_key)
        if spec is None:
            return RedirectResponse("/resources", status_code=303)
        catalog = await _catalog()
        try:
            list_operation = resolve_operation(catalog, spec.list_operation_id)
            create_operation = resolve_operation(catalog, spec.create_operation_id)
        except MissingOperation as exc:
            return state.templates.TemplateResponse(
                request,
                "resources/list.html",
                state.context(
                    request,
                    spec=spec,
                    rows=[],
                    next_cursor="",
                    list_error=f"control plane no longer exposes {exc.operation_id}",
                    create_inputs=[],
                ),
            )
        rows: list[dict[str, Any]] = []
        list_error = ""
        cursor = ""
        if list_operation is not None:
            response = await state.control_request(
                list_operation.method,
                list_operation.path_template,
                bearer=_bearer(request),
                params=pagination_params(list_operation, request.query_params) or None,
            )
            if response.ok:
                rows = [
                    {
                        "id": item_reference(item, spec.item_key),
                        "columns": scalar_columns(item, spec.columns),
                        "item": item,
                    }
                    for item in list_items(response.payload)
                ]
                cursor = next_cursor(response.payload)
            else:
                list_error = _error_text(response)
        return state.templates.TemplateResponse(
            request,
            "resources/list.html",
            state.context(
                request,
                spec=spec,
                rows=rows,
                next_cursor=cursor,
                list_error=list_error,
                create_inputs=build_inputs(
                    create_operation, secret_fields=spec.create_secret_fields
                )
                if create_operation is not None
                else [],
            ),
        )

    async def resource_detail(request: Request, resource_key: str, item_id: str) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        spec = spec_by_key(resource_key)
        if spec is None or spec.get_operation_id is None or spec.item_param is None:
            return RedirectResponse("/resources", status_code=303)
        catalog = await _catalog()
        try:
            get_operation = resolve_operation(catalog, spec.get_operation_id)
            actions = [
                (action, resolve_operation(catalog, action.operation_id)) for action in spec.actions
            ]
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert get_operation is not None
        response = await state.control_request(
            get_operation.method,
            get_operation.path_template.replace("{" + spec.item_param + "}", item_id),
            bearer=_bearer(request),
        )
        item = as_mapping(response.payload)
        return state.templates.TemplateResponse(
            request,
            "resources/detail.html",
            state.context(
                request,
                spec=spec,
                item_id=item_id,
                item=item,
                item_error="" if response.ok else _error_text(response),
                detail=summarize_payload(item),
                actions=[
                    _action_context(
                        request,
                        operation,
                        action_url=f"/resources/{spec.key}/{item_id}/actions/{action.key}",
                        form_id=f"action-{action.key}",
                        values={
                            str(spec.item_param): item_id,
                            **prefill_values(item, action.prefill),
                        },
                        secret_fields=action.secret_fields,
                        submit_label=action.label,
                        danger=action.danger,
                        confirm=action.confirm,
                        description=action.description,
                    )
                    for action, operation in actions
                ],
            ),
        )

    async def resource_create(request: Request, resource_key: str) -> Response:
        spec = spec_by_key(resource_key)
        if spec is None or spec.create_operation_id is None:
            return RedirectResponse("/resources", status_code=303)
        return await _run_action(request, spec.create_operation_id, form_id="create")

    async def resource_action(
        request: Request, resource_key: str, item_id: str, action_key: str
    ) -> Response:
        spec = spec_by_key(resource_key)
        if spec is None:
            return RedirectResponse("/resources", status_code=303)
        action = next((item for item in spec.actions if item.key == action_key), None)
        if action is None:
            return RedirectResponse(f"/resources/{resource_key}", status_code=303)
        return await _run_action(request, action.operation_id, form_id=f"action-{action_key}")

    # -------------------------------------------------------- configurations

    async def configurations(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            list_operation = resolve_operation(catalog, CONFIGURATION_OPERATION_IDS["list"])
            policy_operation = resolve_operation(
                catalog, CONFIGURATION_OPERATION_IDS["recovery_policy"]
            )
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert list_operation is not None
        response = await state.control_request(
            list_operation.method, list_operation.path_template, bearer=_bearer(request)
        )
        kinds: dict[str, int] = {}
        if response.ok:
            for item in list_items(response.payload):
                kind = str(item.get("configuration_kind", "?"))
                kinds[kind] = kinds.get(kind, 0) + 1
        policy: dict[str, Any] = {}
        if policy_operation is not None:
            policy_response = await state.control_request(
                policy_operation.method, policy_operation.path_template, bearer=_bearer(request)
            )
            if policy_response.ok:
                policy = as_mapping(policy_response.payload)
        return state.templates.TemplateResponse(
            request,
            "resources/configurations.html",
            state.context(
                request,
                kinds=sorted(kinds.items()),
                policy=policy,
                policy_detail=summarize_payload(policy) if policy else ([], []),
                list_error="" if response.ok else _error_text(response),
            ),
        )

    async def configuration_kind(request: Request, kind: str) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            revision_list = resolve_operation(catalog, CONFIGURATION_OPERATION_IDS["revision_list"])
            stage_operation = resolve_operation(catalog, CONFIGURATION_OPERATION_IDS["stage"])
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert revision_list is not None
        response = await state.control_request(
            revision_list.method,
            revision_list.path_template.replace("{configuration_kind}", kind),
            bearer=_bearer(request),
        )
        revisions = list_items(response.payload) if response.ok else []
        active = next(
            (str(item.get("revision")) for item in revisions if item.get("state") == "active"),
            "",
        )
        stage_values = {"configuration_kind": kind}
        return state.templates.TemplateResponse(
            request,
            "resources/revisions.html",
            state.context(
                request,
                kind=kind,
                revisions=revisions,
                active_revision=active,
                revisions_error="" if response.ok else _error_text(response),
                stage=_action_context(
                    request,
                    stage_operation,
                    action_url=f"/resources/configurations/{kind}/stage",
                    form_id="stage",
                    values=stage_values,
                    submit_label="Stage revision",
                ),
            ),
        )

    async def configuration_revision(request: Request, kind: str, revision: str) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            revision_get = resolve_operation(catalog, CONFIGURATION_OPERATION_IDS["revision_get"])
            revision_list = resolve_operation(catalog, CONFIGURATION_OPERATION_IDS["revision_list"])
            resolved = {
                key: resolve_operation(catalog, operation_id)
                for key, operation_id in _CONFIG_ACTIONS.items()
            }
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert revision_get is not None and revision_list is not None
        detail_response = await state.control_request(
            revision_get.method,
            revision_get.path_template.replace("{configuration_kind}", kind).replace(
                "{revision}", revision
            ),
            bearer=_bearer(request),
        )
        payload = as_mapping(detail_response.payload)
        list_response = await state.control_request(
            revision_list.method,
            revision_list.path_template.replace("{configuration_kind}", kind),
            bearer=_bearer(request),
        )
        active = next(
            (
                str(item.get("revision"))
                for item in list_items(list_response.payload)
                if item.get("state") == "active"
            ),
            "",
        )
        base_values = {"configuration_kind": kind, "revision": revision}
        actions: list[dict[str, Any]] = []
        for key, operation in resolved.items():
            values = dict(base_values)
            if key == "activate":
                values["expected_active_revision"] = active
            actions.append(
                _action_context(
                    request,
                    operation,
                    action_url=f"/resources/configurations/{kind}/{revision}/actions/{key}",
                    form_id=f"action-{key}",
                    values=values,
                    submit_label=key.title(),
                    danger=key == "disable",
                    confirm=f"{key.title()} this configuration revision?",
                )
            )
        return state.templates.TemplateResponse(
            request,
            "resources/revision_detail.html",
            state.context(
                request,
                kind=kind,
                revision=revision,
                item=payload,
                item_error="" if detail_response.ok else _error_text(detail_response),
                detail=summarize_payload(payload),
                actions=actions,
            ),
        )

    async def configuration_stage(request: Request, kind: str) -> Response:
        return await _run_action(request, CONFIGURATION_OPERATION_IDS["stage"], form_id="stage")

    async def configuration_action(
        request: Request, kind: str, revision: str, action_key: str
    ) -> Response:
        operation_id = _CONFIG_ACTIONS.get(action_key)
        if operation_id is None:
            return RedirectResponse(f"/resources/configurations/{kind}", status_code=303)
        return await _run_action(request, operation_id, form_id=f"action-{action_key}")

    # --------------------------------------------------------------- secrets

    def _secret_form(
        request: Request,
        operation: AdminOperation | None,
        action_key: str,
        secret_fields: tuple[str, ...],
        label: str,
    ) -> dict[str, Any]:
        return _action_context(
            request,
            operation,
            action_url=f"/resources/secrets/actions/{action_key}",
            form_id=f"secret-{action_key}",
            secret_fields=secret_fields,
            submit_label=label,
        )

    async def secrets(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            create_operation = resolve_operation(catalog, SECRET_OPERATION_IDS["create"])
            keyring_operation = resolve_operation(catalog, SECRET_OPERATION_IDS["keyring_create"])
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        return state.templates.TemplateResponse(
            request,
            "resources/secrets.html",
            state.context(
                request,
                note=_note("secrets"),
                create=_secret_form(
                    request, create_operation, "create", ("value",), "Create secret"
                ),
                keyring=_secret_form(
                    request,
                    keyring_operation,
                    "keyring-create",
                    (),
                    "Create appointment signing keyring",
                ),
            ),
        )

    async def secret_detail(request: Request, binding_id: str) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            metadata = resolve_operation(catalog, SECRET_OPERATION_IDS["metadata_get"])
            rotate = resolve_operation(catalog, SECRET_OPERATION_IDS["rotate"])
            keyring_rotate = resolve_operation(catalog, SECRET_OPERATION_IDS["keyring_rotate"])
            revoke = resolve_operation(catalog, SECRET_OPERATION_IDS["revoke"])
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert metadata is not None
        response = await state.control_request(
            metadata.method,
            metadata.path_template.replace("{binding_id}", binding_id),
            bearer=_bearer(request),
        )
        payload = as_mapping(response.payload)
        purpose = str(payload.get("purpose", ""))
        is_keyring = purpose == "security.appointment_option_signing"
        revision_values = {
            "binding_id": binding_id,
            "expected_revision": str(payload.get("revision", "")),
            "expected_backend_version": str(payload.get("backend_version", "")),
        }
        rotate_operation = keyring_rotate if is_keyring else rotate
        return state.templates.TemplateResponse(
            request,
            "resources/secret_detail.html",
            state.context(
                request,
                binding_id=binding_id,
                item=payload,
                item_error="" if response.ok else _error_text(response),
                detail=summarize_payload(payload),
                detail_kind="keyring" if is_keyring else "secret",
                rotate=_action_context(
                    request,
                    rotate_operation,
                    action_url="/resources/secrets/actions/rotate"
                    if not is_keyring
                    else "/resources/secrets/actions/keyring-rotate",
                    form_id="secret-rotate",
                    values=revision_values,
                    secret_fields=() if is_keyring else ("value",),
                    submit_label="Rotate",
                    danger=True,
                    confirm="Rotate this secret?",
                ),
                revoke=_action_context(
                    request,
                    revoke,
                    action_url="/resources/secrets/actions/revoke",
                    form_id="secret-revoke",
                    values=revision_values,
                    submit_label="Revoke",
                    danger=True,
                    confirm="Revoke this secret? This cannot be undone.",
                ),
            ),
        )

    async def secret_action(request: Request, action_key: str) -> Response:
        entry = _SECRET_ACTIONS.get(action_key)
        if entry is None:
            return RedirectResponse("/resources/secrets", status_code=303)
        operation_id, _ = entry
        return await _run_action(request, operation_id, form_id=f"secret-{action_key}")

    # ------------------------------------------------------------ deployment

    async def deployment(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            plan = resolve_operation(catalog, DEPLOYMENT_OPERATION_IDS["plan"])
            configure = resolve_operation(catalog, DEPLOYMENT_OPERATION_IDS["configure"])
            reconcile = resolve_operation(catalog, DEPLOYMENT_OPERATION_IDS["reconcile"])
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        assert plan is not None
        response = await state.control_request(
            plan.method, plan.path_template, bearer=_bearer(request)
        )
        payload = as_mapping(response.payload)
        binding = as_mapping(payload.get("binding"))
        configure_values = {
            "expected_active_revision": str(binding.get("revision", "")),
            "base_url": str(binding.get("base_url", "")),
            "database_uuid": str(binding.get("database_uuid", "")),
            "secret_binding_id": str(binding.get("secret_binding_id", "")),
        }
        return state.templates.TemplateResponse(
            request,
            "resources/deployment.html",
            state.context(
                request,
                item=payload,
                item_error="" if response.ok else _error_text(response),
                detail=summarize_payload(payload),
                configure=_action_context(
                    request,
                    configure,
                    action_url="/resources/deployment-recovery/actions/configure",
                    form_id="configure",
                    values=configure_values,
                    submit_label="Save binding",
                ),
                reconcile=_action_context(
                    request,
                    reconcile,
                    action_url="/resources/deployment-recovery/actions/reconcile",
                    form_id="reconcile",
                    submit_label="Reconcile",
                    confirm="Reconcile the deployment binding with Coolify?",
                ),
            ),
        )

    async def deployment_action(request: Request, action_key: str) -> Response:
        operation_id = _DEPLOYMENT_ACTIONS.get(action_key)
        if operation_id is None:
            return RedirectResponse("/resources/deployment-recovery", status_code=303)
        return await _run_action(request, operation_id, form_id=action_key)

    # ---------------------------------------------------------------- owners

    async def owners(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            resolved = {
                key: resolve_operation(catalog, operation_id)
                for key, operation_id in _OWNER_ACTIONS.items()
            }
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        forms = {
            key: _action_context(
                request,
                operation,
                action_url=f"/resources/owners/actions/{key}",
                form_id=f"owner-{key}",
                submit_label=_owner_label(key),
                danger=key in {"revoke-invitation", "suspend", "revoke"},
                confirm=f"{_owner_label(key)}?",
            )
            for key, operation in resolved.items()
        }
        return state.templates.TemplateResponse(
            request,
            "resources/owners.html",
            state.context(
                request,
                note=_note("owners"),
                forms=forms,
            ),
        )

    async def owners_action(request: Request, action_key: str) -> Response:
        operation_id = _OWNER_ACTIONS.get(action_key)
        if operation_id is None:
            return RedirectResponse("/resources/owners", status_code=303)
        return await _run_action(request, operation_id, form_id=f"owner-{action_key}")

    # ---------------------------------------------------------- provisioning

    async def provisioning(request: Request) -> Response:
        if _session(request) is None:
            return RedirectResponse("/login", status_code=303)
        catalog = await _catalog()
        try:
            resolved = {
                key: resolve_operation(catalog, operation_id)
                for key, operation_id in _PROVISIONING_ACTIONS.items()
            }
        except MissingOperation as exc:
            return _drift(request, exc.operation_id)
        forms = {
            key: _action_context(
                request,
                operation,
                action_url=f"/resources/provisioning/actions/{key}",
                form_id=f"provisioning-{key}",
                submit_label="Create organization"
                if key == "organization"
                else "Create recovery operator",
            )
            for key, operation in resolved.items()
        }
        return state.templates.TemplateResponse(
            request,
            "resources/provisioning.html",
            state.context(
                request,
                note=_note("provisioning"),
                forms=forms,
            ),
        )

    async def provisioning_action(request: Request, action_key: str) -> Response:
        operation_id = _PROVISIONING_ACTIONS.get(action_key)
        if operation_id is None:
            return RedirectResponse("/resources/provisioning", status_code=303)
        return await _run_action(request, operation_id, form_id=f"provisioning-{action_key}")

    # ------------------------------------------------------------ registration

    app.add_api_route(
        "/resources/configurations",
        configurations,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/configurations/{kind}",
        configuration_kind,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/configurations/{kind}/{revision}",
        configuration_revision,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/configurations/{kind}/stage",
        configuration_stage,
        methods=["POST"],
    )
    app.add_api_route(
        "/resources/configurations/{kind}/{revision}/actions/{action_key}",
        configuration_action,
        methods=["POST"],
    )
    app.add_api_route("/resources/secrets", secrets, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        "/resources/secrets/actions/{action_key}",
        secret_action,
        methods=["POST"],
    )
    app.add_api_route(
        "/resources/secrets/{binding_id}",
        secret_detail,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/deployment-recovery",
        deployment,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/deployment-recovery/actions/{action_key}",
        deployment_action,
        methods=["POST"],
    )
    app.add_api_route("/resources/owners", owners, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/resources/owners/actions/{action_key}", owners_action, methods=["POST"])
    app.add_api_route(
        "/resources/provisioning",
        provisioning,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/provisioning/actions/{action_key}",
        provisioning_action,
        methods=["POST"],
    )

    app.add_api_route("/resources", resources_index, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route(
        "/resources/{resource_key}",
        resource_list,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route(
        "/resources/{resource_key}/{item_id}",
        resource_detail,
        methods=["GET"],
        response_class=HTMLResponse,
    )
    app.add_api_route("/resources/{resource_key}", resource_create, methods=["POST"])
    app.add_api_route(
        "/resources/{resource_key}/{item_id}/actions/{action_key}",
        resource_action,
        methods=["POST"],
    )


def _error_text(response: Any) -> str:
    body = response.error_body
    code = body.get("code") if body else None
    if isinstance(code, str):
        return code
    return f"control_error_{response.status_code}"


def _owner_label(key: str) -> str:
    return key.replace("-", " ").title()


def _note(key: str) -> str:
    spec = workspace_by_key(key)
    return spec.no_list_note if spec is not None else ""


__all__ = ["install_resource_routes"]
