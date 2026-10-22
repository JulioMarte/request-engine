"""Plain-language names for capability keys, for display only.

This is interface copy, not policy: it never decides what a capability allows,
who may hold it or whether an agent may use it. Unknown keys fall back to a
readable form of the key itself, so a new owner capability is never hidden.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

_GROUPS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Citas",
        (
            ("appointments.find_slots", "Buscar horarios libres"),
            ("appointments.book", "Reservar citas"),
            ("appointments.reschedule", "Cambiar la fecha de citas"),
            ("appointments.cancel", "Cancelar citas"),
            ("appointments.read", "Ver detalles de citas"),
            ("appointments.day_board", "Ver las citas del día"),
            ("appointments.confirm_attendance", "Registrar si el paciente viene"),
            ("appointments.record_arrival_estimate", "Registrar hora de llegada"),
            ("appointments.subject_override", "Actuar por cualquier paciente en citas"),
        ),
    ),
    (
        "Recepción y filas de espera",
        (
            ("queue.list", "Ver filas de espera"),
            ("queue.status", "Ver el turno de un paciente"),
            ("queue.staff_read", "Ver la fila en vivo"),
            ("queue.staff_history_read", "Ver historial de la fila"),
            ("queue.join", "Agregar pacientes a una fila"),
            ("queue.leave", "Sacar pacientes de una fila"),
            ("queue.check_in", "Registrar llegada de pacientes"),
            ("queue.call_next", "Llamar al siguiente"),
            ("queue.skip", "Saltar a un paciente"),
            ("queue.mark_no_show", "Marcar que no se presentó"),
            ("queue.operator_select", "Llamar a un paciente específico"),
            ("queue.recall_hold", "Apartar a un paciente"),
            ("queue.release_recall_hold", "Devolver a la fila"),
            ("queue.classify_expected_workload", "Indicar duración esperada de la atención"),
            ("queue.subject_override", "Actuar por cualquier paciente en filas"),
            ("queue.configure", "Configurar filas de espera"),
            ("queue.read_configuration", "Ver configuración de filas"),
            ("queue.manage_intake", "Abrir o cerrar la entrada a la fila"),
        ),
    ),
    (
        "Atención en curso",
        (
            ("service_session.start", "Iniciar atención"),
            ("service_session.pause", "Pausar atención"),
            ("service_session.resume", "Reanudar atención"),
            ("service_session.complete", "Terminar atención"),
            ("service_session.read", "Ver atenciones en curso"),
            ("resource_activity.start", "Iniciar actividad de médico o consultorio"),
            ("resource_activity.end", "Terminar actividad de médico o consultorio"),
            ("resource_activity.read", "Ver actividad de médicos y consultorios"),
            ("workload.list", "Ver duraciones de atención"),
            ("workload.create", "Agregar duraciones de atención"),
            ("workload.update", "Cambiar duraciones de atención"),
            ("workload.deactivate", "Retirar duraciones de atención"),
        ),
    ),
    (
        "Pacientes",
        (
            ("parties.register", "Registrar pacientes"),
            ("parties.lookup", "Buscar pacientes"),
            ("parties.rename", "Cambiar nombre de pacientes"),
            ("parties.add_contact_point", "Agregar contactos de pacientes"),
            ("parties.confirm_contact_point", "Confirmar contactos de pacientes"),
            ("parties.deactivate_contact_point", "Quitar contactos de pacientes"),
            ("parties.add_document", "Agregar documentos de pacientes"),
            ("parties.add_administrative_identifier", "Agregar identificaciones de pacientes"),
            ("parties.lookup_administrative_identifier", "Buscar pacientes por identificación"),
            ("parties.read_revisions", "Ver historial de cambios de pacientes"),
            ("parties.deactivate", "Desactivar pacientes"),
            ("parties.rollback_identity", "Deshacer cambios de identidad de pacientes"),
        ),
    ),
    (
        "Solicitudes",
        (
            ("requests.submit", "Enviar solicitudes"),
            ("requests.read", "Ver solicitudes"),
            ("requests.read_inbox", "Ver la bandeja de solicitudes"),
            ("requests.cancel", "Cancelar solicitudes"),
            ("requests.read_definitions", "Ver tipos de solicitud"),
            ("requests.create_definition", "Crear tipos de solicitud"),
            ("requests.publish_definition_version", "Publicar tipos de solicitud"),
            ("requests.set_definition_active", "Activar o desactivar tipos de solicitud"),
            ("requests.party_override", "Actuar por cualquier paciente en solicitudes"),
        ),
    ),
    (
        "Negocio, servicios y sedes",
        (
            ("business.get_info", "Ver información del negocio"),
            ("organization.manage_profile", "Editar el perfil del negocio"),
            ("organization.bootstrap", "Configurar el negocio"),
            ("catalog.search_offerings", "Buscar servicios"),
            ("catalog.get_offering_details", "Ver detalles de servicios"),
            ("catalog.manage", "Administrar servicios y sedes"),
            ("catalog.read_configuration", "Ver configuración de servicios y sedes"),
            ("booking.manage_supply", "Administrar disponibilidad, médicos y consultorios"),
            ("booking.read_supply", "Ver disponibilidad, médicos y consultorios"),
            ("communications.configure", "Configurar mensajes"),
            ("communications.read_configuration", "Ver configuración de mensajes"),
            ("discovery.manage", "Administrar la publicación en el directorio"),
            ("onboarding.read", "Ver el avance de la configuración"),
        ),
    ),
    (
        "Recordatorios y lista de espera",
        (
            ("reminders.create_plan", "Programar recordatorios"),
            ("reminders.cancel_plan", "Cancelar recordatorios"),
            ("reminders.read", "Ver recordatorios"),
            ("reminders.subject_override", "Actuar por cualquier paciente en recordatorios"),
            ("waitlist.join", "Agregar a la lista de espera"),
            ("waitlist.leave", "Sacar de la lista de espera"),
            ("waitlist.read", "Ver la lista de espera"),
            ("waitlist.accept_offer", "Aceptar ofertas de la lista de espera"),
            ("waitlist.decline_offer", "Rechazar ofertas de la lista de espera"),
            ("waitlist.subject_override", "Actuar por cualquier paciente en la lista de espera"),
        ),
    ),
    (
        "Capacidad y recuperación",
        (
            ("live_capacity.read", "Ver capacidad en vivo"),
            ("live_capacity.customer_read", "Ver tiempos de espera estimados"),
            ("live_capacity.evaluate_intake", "Revisar si caben más pacientes"),
            ("live_capacity.configure_scope", "Configurar el seguimiento de capacidad"),
            ("live_capacity.configure_estimate", "Configurar tiempos de espera estimados"),
            ("operational_recovery.read", "Ver planes de recuperación"),
            ("operational_recovery.propose", "Proponer planes de recuperación"),
            ("operational_recovery.execute", "Ejecutar planes de recuperación"),
            ("operational_recovery.configure_autonomy", "Configurar recuperación automática"),
        ),
    ),
    (
        "Equipo y acceso",
        (
            ("staff.read", "Ver el equipo"),
            ("staff.invite", "Invitar personas"),
            ("staff.propose_invitation", "Sugerir personas para invitar"),
            ("staff.manage_membership", "Activar o suspender miembros del equipo"),
            ("staff.manage_authority", "Cambiar permisos del equipo"),
            ("staff.plan_authority", "Revisar cambios de permisos antes de aplicarlos"),
            ("staff.manage_own_admin_contact", "Administrar su contacto de administración"),
            ("staff.confirm_own_admin_contact", "Confirmar su contacto de administración"),
            ("authority.read_self", "Ver sus propios permisos"),
            ("authority.inspect_resource", "Ver quién puede actuar sobre un elemento"),
            ("delegation.create", "Delegar tareas"),
            ("delegation.revoke", "Retirar tareas delegadas"),
            ("controller_policy_upgrade", "Actualizar permisos del dueño"),
            ("identity.bind", "Conectar cuentas de inicio de sesión"),
            ("identity.binding.read", "Ver cuentas de inicio de sesión conectadas"),
            ("identity.link_self", "Vincular sus cuentas de inicio de sesión"),
            ("identity_exchange.publish", "Publicar coincidencias de identidad"),
            ("identity_exchange.match", "Buscar coincidencias de identidad"),
            ("identity_exchange.adopt", "Adoptar identidades coincidentes"),
        ),
    ),
    (
        "Asistentes e integraciones",
        (
            ("agent.read", "Ver asistentes"),
            ("agent.provision", "Crear asistentes"),
            ("agent.manage_authority", "Cambiar permisos y claves de asistentes"),
            ("agent.manage_policy", "Cambiar límites de seguridad de asistentes"),
            ("agent.policy.read", "Ver límites de seguridad de asistentes"),
            ("agent.suspend", "Pausar o revocar asistentes"),
            ("integration.read", "Ver integraciones"),
            ("integration.provision", "Crear integraciones"),
            ("integration.manage_authority", "Cambiar permisos y claves de integraciones"),
            ("integration.suspend", "Pausar o revocar integraciones"),
            ("operational_copilot.read", "Consultar con el asistente anterior"),
            ("operational_copilot.interpret", "Usar la interpretación del asistente anterior"),
            ("operational_copilot.execute", "Usar acciones del asistente anterior"),
        ),
    ),
)

_BY_KEY: dict[str, tuple[str, str]] = {
    key: (group, label) for group, entries in _GROUPS for key, label in entries
}
_GROUP_ORDER = {group: index for index, (group, _) in enumerate(_GROUPS)}
_OTHER = "Otros"


@dataclass(frozen=True)
class CapabilityLabel:
    key: str
    group: str
    label: str


def capability_label(key: str) -> CapabilityLabel:
    group, label = _BY_KEY.get(key, (_OTHER, key.replace("_", " ").replace(".", ": ").capitalize()))
    return CapabilityLabel(key=key, group=group, label=label)


def grouped_capabilities(keys: Iterable[str]) -> list[tuple[str, list[CapabilityLabel]]]:
    """Group keys for display, keeping the owner's keys intact as data."""

    grouped: dict[str, list[CapabilityLabel]] = {}
    for key in sorted(set(keys)):
        item = capability_label(key)
        grouped.setdefault(item.group, []).append(item)
    order = sorted(grouped, key=lambda group: _GROUP_ORDER.get(group, len(_GROUP_ORDER)))
    return [(group, sorted(grouped[group], key=lambda item: item.label)) for group in order]


__all__ = ["CapabilityLabel", "capability_label", "grouped_capabilities"]
