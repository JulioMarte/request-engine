"""Owner-facing names and next steps for onboarding readiness, for display only.

The onboarding API's area keys and resolution hints are written for
integrations; the console says what the person should do in their own terms.
This copy never decides readiness: the onboarding owner does.
"""

from __future__ import annotations

_LABELS = {
    "business_party": "Datos del negocio",
    "locations": "Sedes",
    "appointments": "Citas",
    "walk_in_queue": "Fila de espera sin cita",
    "communications": "Mensajes",
    "identity": "Inicio de sesión",
    "tenant_control": "Control del dueño",
    "staff_administration": "Administración del equipo",
    "recovery": "Recuperación de acceso",
}
# Owner-facing next steps. The onboarding API's resolution hints are written for
# integrations; the console says what the person should do in their own terms.
_GUIDANCE = {
    "business_party": (
        "Los datos de su negocio están incompletos. Pídale ayuda al administrador de la plataforma."
    ),
    "locations": "Agregue la sede donde atiende a sus pacientes, con su horario.",
    "appointments": (
        "Agregue un servicio con su precio y un médico o consultorio con su horario semanal, "
        "para que sus pacientes puedan reservar."
    ),
    "walk_in_queue": "Cree una fila de espera para los pacientes que llegan sin cita.",
    "communications": "Elija cómo les llegan las confirmaciones y recordatorios a sus pacientes.",
    "identity": (
        "El inicio de sesión de este negocio no está listo. "
        "Pídale ayuda al administrador de la plataforma."
    ),
    "tenant_control": "Hay nuevos permisos del dueño disponibles. Solicite la actualización.",
    "staff_administration": (
        "La administración del equipo no está lista. "
        "Pídale ayuda al administrador de la plataforma."
    ),
    "recovery": (
        "Guarde sus códigos de recuperación en Seguridad de la cuenta, "
        "para poder entrar si olvida su contraseña."
    ),
}
_STATES = {"ready": "Listo", "blocked": "Pendiente", "unknown": "Sin verificar"}


def readiness_label(key: str) -> str:
    return _LABELS.get(key, key.replace("_", " ").capitalize())


def readiness_state(status: str) -> str:
    return _STATES.get(status, status.capitalize())


def readiness_guidance(key: str) -> str:
    return _GUIDANCE.get(key, "")
