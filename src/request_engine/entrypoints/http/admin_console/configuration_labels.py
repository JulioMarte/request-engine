"""Plain, unique names for configuration tasks, for display only.

This is interface copy, not policy: it never decides what an operation does,
who may run it or which owner handles it. The owner's OpenAPI summary is
written for integrators ("Create", "Offering") and repeats across sections, so
the console names each task by what a business person is doing. Unknown
operations fall back to the owner's summary, so a new task is never hidden.
"""

from __future__ import annotations

from typing import Any

_LABELS = {
    # Organization
    "parties_register": "Registrar un paciente o contacto",
    "business_get_info": "Ver datos del negocio",
    "tenancy_operational_authority_bootstrap": "Definir quién puede administrar el negocio",
    "tenancy_organization_profile_update": "Cambiar el perfil del negocio",
    "tenancy_organization_contacts_replace": "Cambiar los contactos del negocio",
    # Locations and hours
    "catalog_location_configuration_list": "Ver todas las sedes",
    "catalog_location_configuration_read": "Ver una sede",
    "catalog_location_create": "Agregar una sede",
    "catalog_location_update": "Cambiar una sede",
    "catalog_location_contacts_update": "Cambiar los contactos de una sede",
    "catalog_location_hours_replace": "Cambiar el horario",
    "catalog_location_hours_exception_upsert": "Poner un horario especial para una fecha",
    "catalog_organization_holidays_replace": "Definir días feriados",
    "catalog_location_hours_exception_list": "Ver horarios especiales y feriados de una sede",
    "catalog_location_hours_exception_deactivate": "Quitar un horario especial de una sede",
    "catalog_organization_holidays_remove": "Quitar días feriados",
    # Services and booking policies
    "catalog_offering_configuration_list": "Ver todos los servicios",
    "catalog_offering_configuration_read": "Ver un servicio",
    "catalog_resource_capabilities_list": "Ver especialidades y tipos de equipo",
    "catalog_manage_resource_capabilities": "Agregar una especialidad o tipo de equipo",
    "catalog_manage_offerings": "Agregar un servicio",
    "catalog_offering_version_configuration_read": "Ver la configuración actual de un servicio",
    "catalog_manage_offering_version_booking_policy": (
        "Cambiar las reglas de reserva de un servicio"
    ),
    "catalog_offering_booking_terms_configure": "Poner el precio de un servicio",
    "catalog_offering_update": "Cambiar el nombre de un servicio",
    "catalog_offering_version_supersede": "Cambiar la duración o el precio de un servicio",
    # Resources and supply
    "booking_resource_list": "Ver médicos, consultorios y equipos",
    "booking_resource_create": "Agregar un médico, consultorio o equipo",
    "booking_resource_update": "Cambiar el nombre de un médico, consultorio o equipo",
    "booking_resource_capabilities_replace": "Cambiar los servicios que ofrece un médico o equipo",
    "booking_resource_assignment_list": "Ver quién trabaja en cada sede",
    "booking_resource_assignment_create": "Asignar a una sede",
    "booking_resource_assignment_retire": "Terminar una asignación",
    "booking_resource_assignment_availability_list": "Ver el horario semanal",
    "booking_resource_assignment_availability_replace": "Cambiar el horario semanal",
    "booking_resource_assignment_exception_list": "Ver ausencias en una sede",
    "booking_resource_assignment_exception_set": "Registrar una ausencia en una sede",
    "booking_resource_exception_list": "Ver ausencias",
    "booking_resource_exception_set": "Registrar una ausencia",
    "booking_context_terms_list": "Ver precios por sede",
    "booking_context_terms_configure": "Poner un precio para una sede",
    "booking_context_terms_supersede": "Reemplazar el precio de una sede",
    # Service queues
    "queue_service_queue_configuration_list": "Ver todas las filas de espera",
    "queue_service_queue_configuration_read": "Ver una fila de espera",
    "queue_service_queue_create": "Agregar una fila de espera",
    "queue_service_queue_set_active": "Cerrar o reabrir una fila de espera",
    # Requests and definitions
    "request_definitions_list": "Ver tipos de solicitud",
    "request_definition_read": "Ver un tipo de solicitud",
    "requests_list_inbox": "Ver la bandeja de solicitudes",
    "requests_read": "Ver una solicitud",
    "request_definition_create": "Agregar un tipo de solicitud",
    "request_definition_version_publish": "Publicar un nuevo formulario de solicitud",
    "request_definition_set_active": "Activar o desactivar un tipo de solicitud",
    # Public discovery
    "discovery_offering_classification_set": "Publicar un servicio en el directorio",
    "discovery_offering_classification_revoke": "Quitar un servicio del directorio",
    "discovery_resource_public_profile_set": "Definir un perfil público",
    "discovery_resource_public_profile_deactivate": "Ocultar un perfil público",
    "discovery_supply_publish": "Publicar disponibilidad",
    "discovery_publication_revoke": "Retirar la disponibilidad publicada",
    # Agents
    "agent_list": "Ver asistentes",
    "agent_get": "Ver un asistente",
    "agent_provision": "Agregar un asistente",
    "agent_manage_authority": "Cambiar lo que puede hacer un asistente",
    "agent_policy_read": "Ver los límites de seguridad de un asistente",
    "agent_policy_replace": "Cambiar los límites de seguridad de un asistente",
    "agent_suspend": "Pausar o reanudar un asistente",
    "agent_credential_rotate": "Reemplazar la clave de un asistente",
    # Integrations
    "integration_list": "Ver integraciones",
    "integration_read": "Ver una integración",
    "integration_provision": "Agregar una integración",
    "integration_manage_authority": "Cambiar lo que puede hacer una integración",
    "integration_activate_command": "Activar una integración",
    "integration_suspend": "Cambiar el estado de una integración",
    "integration_suspend_command": "Pausar una integración",
    "integration_revoke_command": "Eliminar una integración",
    "integration_credential_rotate": "Reemplazar la clave de una integración",
    # Authority and controller policy
    "authority_read_self": "Ver sus propios permisos",
    "authority_inspect_resource": "Ver quién puede actuar sobre un elemento",
    "delegation_create": "Delegar una tarea",
    "delegation_revoke": "Retirar una tarea delegada",
    "controller_policy_adoption_request_create": "Solicitar permisos del dueño más recientes",
    "controller_policy_adoption_request_get": "Ver una solicitud de permisos",
    "controller_policy_adoption_request_withdraw": "Retirar una solicitud de permisos",
    "controller_policy_upgrade": "Actualizar permisos del dueño (operador)",
    # Identity connections
    "identity_binding_list": "Ver inicios de sesión conectados",
    "identity_binding_get": "Ver un inicio de sesión conectado",
    "identity_binding_suspend": "Pausar un inicio de sesión conectado",
    "identity_binding_reactivate": "Reanudar un inicio de sesión conectado",
    "identity_binding_revoke": "Eliminar un inicio de sesión conectado",
    "identity_exchange_publish": "Compartir el perfil de un paciente con otro negocio",
    "identity_exchange_match": "Buscar un perfil de paciente compartido",
    "identity_exchange_adopt": "Adoptar un perfil de paciente compartido",
    "identity_link_intent_create": "Empezar a vincular un inicio de sesión",
    "identity_link_intent_confirm": "Confirmar la vinculación de un inicio de sesión",
    # Live capacity and recovery policies
    "live_capacity_configure_estimate": "Agregar una regla de tiempo de espera",
    "live_capacity_configure_estimate_update": "Cambiar una regla de tiempo de espera",
    "live_capacity_configure_scope": "Agregar una regla de capacidad",
    "live_capacity_configure_scope_update": "Cambiar una regla de capacidad",
    "live_capacity_read": "Ver la capacidad en vivo de una fila",
    "live_capacity_evaluate_intake": "Revisar si una fila puede recibir más personas",
    "operational_recovery_configure_autonomy": "Configurar la recuperación automática de una fila",
    "workload_list": "Ver duraciones de atención",
    "workload_create": "Agregar una duración de atención",
    "workload_update": "Cambiar una duración de atención",
    "workload_deactivate": "Retirar una duración de atención",
    # Communication channels
    "communications_channel_policy_get": "Ver cómo se envían los mensajes",
    "communications_configure_channel_policy": "Elegir cómo se envían los mensajes",
}


def task_label(operation: Any) -> str:
    """The person-facing name of a configuration task."""

    operation_id = str(getattr(operation, "operation_id", "") or "")
    summary = getattr(operation, "summary", None)
    return _LABELS.get(operation_id) or summary or operation_id.replace("_", " ")
