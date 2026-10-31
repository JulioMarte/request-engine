"""Task-oriented resource model for the admin console.

This is a *presentation* layer over the canonical OpenAPI catalog: specs carry a
stable ``operationId`` and a label, and everything authoritative (method, path,
capability, kind, idempotency, expected-revision policy, request schema) is read
from the control-plane OpenAPI document at request time. It copies no capability
policy and introduces no second execution path: every action still runs through
``execution.execute_operation`` against the same owner operation.

The model is intentionally task-oriented rather than CRUD: Request Engine state
changes are semantic commands, so a resource exposes its real read surface
(list/get when one exists) and its real commands, with revision/binding
preconditions pre-filled from the read.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, AdminOperation
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping


@dataclass(frozen=True)
class ActionSpec:
    key: str
    label: str
    operation_id: str
    description: str = ""
    prefill: tuple[tuple[str, str], ...] = ()
    secret_fields: tuple[str, ...] = ()
    danger: bool = False
    confirm: str = ""


@dataclass(frozen=True)
class ResourceSpec:
    key: str
    title: str
    owner: str
    summary: str
    list_operation_id: str | None = None
    get_operation_id: str | None = None
    item_param: str | None = None
    item_key: str | None = None
    columns: tuple[str, ...] = ()
    create_operation_id: str | None = None
    create_label: str = "Crear"
    create_secret_fields: tuple[str, ...] = ()
    create_prefill: tuple[tuple[str, str], ...] = ()
    actions: tuple[ActionSpec, ...] = ()
    list_note: str = ""

    @property
    def column_headings(self) -> tuple[str, ...]:
        """Spanish table headings; the raw field names stay the data keys."""

        return tuple(COLUMN_HEADINGS.get(column, column) for column in self.columns)


# Presentation-only Spanish headings for the payload fields shown as list columns.
COLUMN_HEADINGS: dict[str, str] = {
    "organization_key": "Clave del negocio",
    "display_name": "Nombre",
    "operational_status": "Estado operativo",
    "default_timezone": "Zona horaria",
    "status": "Estado",
    "revision": "Revisión",
    "created_at": "Creado",
    "principal_kind": "Tipo de principal",
    "active": "Activo",
    "authority_revision": "Revisión de autoridad",
    "binding_status": "Estado del vínculo",
    "delivery_status": "Estado de entrega",
}


@dataclass(frozen=True)
class WorkspaceSpec:
    """A page that is not a simple list/detail resource (configs, secrets, ...)."""

    key: str
    title: str
    owner: str
    summary: str
    no_list_note: str = ""


RESOURCE_SPECS: tuple[ResourceSpec, ...] = (
    ResourceSpec(
        key="organizations",
        title="Negocios",
        owner="tenancy",
        summary="Negocios registrados en la plataforma y su perfil operativo actual.",
        list_operation_id="platform_organization_list",
        get_operation_id="platform_organization_get",
        item_param="organization_id",
        item_key="organization_id",
        columns=("organization_key", "display_name", "operational_status", "default_timezone"),
        create_operation_id="platform_native_organization_create",
        create_label="Crear negocio",
    ),
    ResourceSpec(
        key="native-identities",
        title="Identidades nativas",
        owner="tenancy",
        summary="Identidades nativas de personas y asistentes, su estado y su desactivación.",
        list_operation_id="platform_native_identity_list",
        get_operation_id="platform_native_identity_get",
        item_param="native_identity_id",
        item_key="native_identity_id",
        columns=("status", "revision", "created_at"),
        create_operation_id="platform_native_identity_provision",
        create_label="Crear identidad",
        create_secret_fields=("password",),
        actions=(
            ActionSpec(
                key="disable",
                label="Desactivar",
                operation_id="platform_native_identity_disable",
                description="Desactiva esta identidad. Requiere la revisión actual.",
                prefill=(("expected_revision", "revision"),),
                danger=True,
                confirm="¿Desactivar esta identidad nativa?",
            ),
        ),
    ),
    ResourceSpec(
        key="provisioners",
        title="Aprovisionadores",
        owner="tenancy",
        summary=(
            "Vínculos de aprovisionadores de negocios y su suspensión, reactivación o revocación."
        ),
        list_operation_id="platform_native_provisioner_list",
        get_operation_id="platform_native_provisioner_get",
        item_param="principal_id",
        item_key="principal_id",
        columns=("principal_kind", "active", "authority_revision", "binding_status"),
        create_operation_id="platform_native_provisioner_create",
        create_label="Crear aprovisionador",
        actions=(
            ActionSpec(
                key="suspend",
                label="Suspender",
                operation_id="platform_native_provisioner_suspend",
                description="Suspende el vínculo del aprovisionador.",
                prefill=(("expected_revision", "authority_revision"),),
                danger=True,
                confirm="¿Suspender este aprovisionador?",
            ),
            ActionSpec(
                key="reactivate",
                label="Reactivar",
                operation_id="platform_native_provisioner_reactivate",
                prefill=(("expected_revision", "authority_revision"),),
            ),
            ActionSpec(
                key="revoke",
                label="Revocar",
                operation_id="platform_native_provisioner_revoke",
                prefill=(("expected_revision", "authority_revision"),),
                danger=True,
                confirm="¿Revocar este aprovisionador? Esto no se puede deshacer.",
            ),
        ),
    ),
    ResourceSpec(
        key="recovery-cases",
        title="Casos de recuperación",
        owner="tenancy",
        summary="Casos controlados de recuperación asistida de identidades y su aprobación.",
        list_operation_id="platform_identity_recovery_case_list",
        get_operation_id="platform_identity_recovery_case_get",
        item_param="case_id",
        item_key="case_id",
        columns=("status", "revision", "delivery_status", "created_at"),
        create_operation_id="platform_identity_recovery_case_create",
        create_label="Abrir caso de recuperación",
        actions=(
            ActionSpec(
                key="approve",
                label="Aprobar",
                operation_id="platform_identity_recovery_case_approve",
                prefill=(("expected_revision", "revision"),),
                danger=True,
                confirm="¿Aprobar este caso de recuperación?",
            ),
            ActionSpec(
                key="issue",
                label="Emitir",
                operation_id="platform_identity_recovery_case_issue",
                prefill=(("expected_revision", "revision"),),
                danger=True,
                confirm="¿Emitir el material de recuperación de este caso?",
            ),
            ActionSpec(
                key="revoke",
                label="Revocar",
                operation_id="platform_identity_recovery_case_revoke",
                prefill=(("expected_revision", "revision"),),
                danger=True,
                confirm="¿Revocar este caso de recuperación?",
            ),
        ),
    ),
)

WORKSPACE_SPECS: tuple[WorkspaceSpec, ...] = (
    WorkspaceSpec(
        key="controller-policy-adoptions",
        title="Adopción de la política del controlador",
        owner="tenancy",
        summary=(
            "Revise el consentimiento del negocio y aplique la política actual "
            "del controlador de forma segura."
        ),
    ),
    WorkspaceSpec(
        key="configurations",
        title="Configuración de la plataforma",
        owner="platform_configuration",
        summary=(
            "Revisiones de configuración preparadas, validadas y activas, y pruebas de proveedores."
        ),
    ),
    WorkspaceSpec(
        key="secrets",
        title="Secretos y llaveros de firma",
        owner="platform_configuration",
        summary="Cree, rote y revoque vínculos de secretos de la plataforma por su identificador.",
        no_list_note=(
            "El plano de control muestra los datos de un secreto por el identificador "
            "de su vínculo, pero no tiene una operación para listarlos: los secretos "
            "se buscan, nunca se listan."
        ),
    ),
    WorkspaceSpec(
        key="deployment-recovery",
        title="Recuperación del despliegue",
        owner="platform_configuration",
        summary="Inspeccione el vínculo de despliegue activo y concílielo con Coolify.",
    ),
    WorkspaceSpec(
        key="owners",
        title="Dueños de la plataforma",
        owner="tenancy",
        summary="Invite, registre y gestione a otros dueños de la plataforma.",
    ),
    WorkspaceSpec(
        key="provisioning",
        title="Operadores de recuperación",
        owner="tenancy",
        summary="Cree operadores de recuperación de la plataforma con el comando disponible.",
        no_list_note=(
            "Esta operación solo permite crear: no hay una operación para listar o leer "
            "operadores de recuperación, así que este espacio muestra el comando en vez "
            "de una tabla."
        ),
    ),
)

# Operation ids used by the non-simple workspaces (resolved against the catalog).
CONTROLLER_ADOPTION_OPERATION_IDS = {
    "list": "platform_controller_policy_adoption_list",
    "review": "platform_controller_policy_adoption_review",
    "apply": "platform_controller_policy_adoption_apply",
}
CONFIGURATION_OPERATION_IDS = {
    "list": "platform_configuration_list",
    "revision_list": "platform_configuration_revision_list",
    "revision_get": "platform_configuration_revision_get",
    "stage": "platform_configuration_stage",
    "validate": "platform_configuration_validate",
    "activate": "platform_configuration_activate",
    "disable": "platform_configuration_disable",
    "provider_test": "platform_provider_test",
    "recovery_policy": "platform_recovery_policy_get",
}
SECRET_OPERATION_IDS = {
    "metadata_get": "platform_secret_metadata_get",
    "create": "platform_secret_create",
    "rotate": "platform_secret_rotate",
    "revoke": "platform_secret_revoke",
    "keyring_create": "platform_appointment_signing_keyring_create",
    "keyring_rotate": "platform_appointment_signing_keyring_rotate",
}
DEPLOYMENT_OPERATION_IDS = {
    "plan": "platform_deployment_recovery_plan",
    "configure": "platform_deployment_recovery_configure",
    "reconcile": "platform_deployment_recovery_reconcile",
}
OWNER_OPERATION_IDS = {
    "list": "platform_owner_list",
    "get": "platform_owner_get",
    "invitation_list": "platform_owner_invitation_list",
    "invitation_get": "platform_owner_invitation_get",
    "invite": "platform_owner_invitation_create",
    "revoke_invitation": "platform_owner_invitation_revoke",
    "activate_invitation": "platform_owner_invitation_activate",
    "suspend": "platform_owner_suspend",
    "reactivate": "platform_owner_reactivate",
    "revoke": "platform_owner_revoke",
}
PROVISIONING_OPERATION_IDS = {
    "recovery_operator_create": "platform_native_recovery_operator_create",
}


def spec_by_key(key: str) -> ResourceSpec | None:
    for spec in RESOURCE_SPECS:
        if spec.key == key:
            return spec
    return None


def workspace_by_key(key: str) -> WorkspaceSpec | None:
    for spec in WORKSPACE_SPECS:
        if spec.key == key:
            return spec
    return None


class MissingOperation(RuntimeError):
    """Raised when a spec references an operation the control plane no longer mounts."""

    def __init__(self, operation_id: str) -> None:
        super().__init__(f"el plano de control no ofrece la operación {operation_id!r}")
        self.operation_id = operation_id


def resolve_operation(catalog: AdminCatalog, operation_id: str | None) -> AdminOperation | None:
    if operation_id is None:
        return None
    operation = catalog.by_id().get(operation_id)
    if operation is None:
        raise MissingOperation(operation_id)
    return operation


def payload_path(item: Mapping[str, Any], path: str) -> str:
    """Read a dotted path from a JSON payload, returning '' when absent."""

    current: Any = item
    for part in path.split("."):
        current = as_mapping(current).get(part)
    if current is None:
        return ""
    return str(current)


def prefill_values(item: Mapping[str, Any], pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
    return {field: payload_path(item, path) for field, path in pairs}


def pagination_params(operation: AdminOperation, query: Mapping[str, str]) -> dict[str, str]:
    """Forward only the cursor/limit params the operation actually declares."""

    declared = {
        parameter.name for parameter in operation.parameters if parameter.location == "query"
    }
    params: dict[str, str] = {}
    for name in ("after", "limit"):
        if name in declared and query.get(name):
            params[name] = query[name]
    return params


def item_reference(item: Mapping[str, Any], item_key: str | None) -> str:
    return payload_path(item, item_key) if item_key else ""


def list_items(payload: Any) -> list[dict[str, Any]]:
    return [as_mapping(item) for item in as_list(as_mapping(payload).get("items"))]


def next_cursor(payload: Any) -> str:
    body = as_mapping(payload)
    for key in ("next_after", "next_cursor"):
        value = body.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


__all__ = [
    "ActionSpec",
    "COLUMN_HEADINGS",
    "CONFIGURATION_OPERATION_IDS",
    "CONTROLLER_ADOPTION_OPERATION_IDS",
    "DEPLOYMENT_OPERATION_IDS",
    "MissingOperation",
    "OWNER_OPERATION_IDS",
    "PROVISIONING_OPERATION_IDS",
    "RESOURCE_SPECS",
    "ResourceSpec",
    "SECRET_OPERATION_IDS",
    "WORKSPACE_SPECS",
    "WorkspaceSpec",
    "item_reference",
    "list_items",
    "next_cursor",
    "pagination_params",
    "payload_path",
    "prefill_values",
    "resolve_operation",
    "spec_by_key",
    "workspace_by_key",
]
