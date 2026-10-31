"""Plain-language form handling for the guided "Set up your clinic" flow.

Everything here turns browser fields into the exact bodies the owner operations
declare, or turns owner answers back into words a clinic owner understands. It
holds no business policy: which values are valid, who may change them and what
is unique is still decided by each owner operation. The only choices made here
are presentation conveniences the owner never sees as policy: generated keys
(slugs derived from the names people type) and sensible form defaults.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping

# Spanish (es-DO) calendar words, explicit so output never depends on the OS locale.
WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
DEFAULT_TIMEZONE = "America/Santo_Domingo"
DEFAULT_CURRENCY = "DOP"
DEFAULT_LOCALE = "es-DO"
DEFAULT_COUNTRY = "DO"
MANAGE_PROFILE_SCOPE = "operations.manage_profile"


def long_date(day: date) -> str:
    """``miércoles 21 de octubre``: a business day in Spanish, independent of the OS locale."""

    return f"{WEEKDAYS[day.weekday()]} {day.day} de {MONTHS[day.month - 1]}"


def zone_label(zone_name: str) -> str:
    """``hora de Santo Domingo`` for an IANA zone such as ``America/Santo_Domingo``."""

    city = zone_name.rsplit("/", 1)[-1].replace("_", " ").strip()
    return f"hora de {city}" if city else "hora del negocio"


TIMEZONES = (
    ("America/Santo_Domingo", "República Dominicana"),
    ("America/Puerto_Rico", "Puerto Rico"),
    ("America/New_York", "Estados Unidos, hora del Este"),
    ("America/Bogota", "Colombia"),
    ("America/Mexico_City", "México, hora del Centro"),
    ("Europe/Madrid", "España, península"),
)
CURRENCIES = (
    ("DOP", "Pesos dominicanos (RD$)"),
    ("USD", "Dólares estadounidenses (US$)"),
    ("EUR", "Euros (€)"),
)
LOCALES = (("es-DO", "Español"), ("en-US", "Inglés"))
COUNTRIES = (
    ("DO", "República Dominicana"),
    ("PR", "Puerto Rico"),
    ("US", "Estados Unidos"),
)
PROVINCES = (
    "Azua", "Bahoruco", "Barahona", "Dajabón", "Distrito Nacional", "Duarte", "El Seibo",
    "Elías Piña", "Espaillat", "Hato Mayor", "Hermanas Mirabal", "Independencia", "La Altagracia",
    "La Romana", "La Vega", "María Trinidad Sánchez", "Monseñor Nouel", "Monte Cristi",
    "Monte Plata", "Pedernales", "Peravia", "Puerto Plata", "Samaná", "San Cristóbal",
    "San José de Ocoa", "San Juan", "San Pedro de Macorís", "Sánchez Ramírez", "Santiago",
    "Santiago Rodríguez", "Santo Domingo", "Valverde",
)  # fmt: skip
DURATIONS = (15, 20, 30, 45, 60, 90, 120)
PROVIDER_KINDS = (
    ("doctor", "Médico o especialista"),
    ("staff", "Enfermera, terapeuta u otro personal"),
    ("room", "Consultorio o sala"),
    ("equipment", "Equipo"),
)
_DEFAULT_WEEK = {day: ("08:00", "17:00") for day in range(5)}
_MAX_KEY_CANDIDATES = 50
_INTENT = re.compile(r"^[A-Za-z0-9_-]{8,100}$")
_AMOUNT = re.compile(r"^\d{1,14}(\.\d{1,2})?$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SetupInputError(ValueError):
    """A field the person must correct before anything is sent to the owner."""


def valid_intent(value: str) -> bool:
    return bool(_INTENT.fullmatch(value))


def slugify(name: str, *, fallback: str = "item") -> str:
    """A lowercase ASCII key derived from a display name (presentation only)."""

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60].strip("-")
    return slug or fallback


def _same_name(left: object, right: str) -> bool:
    return isinstance(left, str) and left.strip().casefold() == right.strip().casefold()


def choose_key(
    base: str, existing: Iterable[Mapping[str, Any]], *, key_field: str, display_name: str
) -> tuple[str, Mapping[str, Any] | None]:
    """Pick the key for a new item, or the existing item a resubmission refers to.

    Keys are tried in order (``base``, ``base-2``, ``base-3`` ...). A key already
    used by an item with the same name means the person is submitting the same
    thing again (a refresh, a retry after a partial failure): that item is
    returned so nothing is duplicated. A key used by a differently named item is
    skipped. The owner still enforces key uniqueness itself.
    """

    by_key = {str(item.get(key_field)): item for item in existing}
    for index in range(1, _MAX_KEY_CANDIDATES + 1):
        candidate = base if index == 1 else f"{base[:56]}-{index}"
        item = by_key.get(candidate)
        if item is None:
            return candidate, None
        if _same_name(item.get("display_name"), display_name):
            return candidate, item
    raise SetupInputError("Ya hay demasiados elementos con un nombre parecido. Elija otro nombre.")


def named(existing: Iterable[Mapping[str, Any]], display_name: str) -> Mapping[str, Any] | None:
    return next(
        (item for item in existing if _same_name(item.get("display_name"), display_name)), None
    )


def required_text(values: Mapping[str, str], field: str, message: str, limit: int = 200) -> str:
    value = values.get(field, "").strip()
    if not value:
        raise SetupInputError(message)
    if len(value) > limit:
        raise SetupInputError(f"Use menos de {limit} caracteres.")
    return value


def optional_text(values: Mapping[str, str], field: str, limit: int = 200) -> str | None:
    value = values.get(field, "").strip()
    return value[:limit] if value else None


def choice(
    values: Mapping[str, str], field: str, options: Iterable[tuple[str, str]], default: str
) -> str:
    value = values.get(field, "").strip() or default
    if value not in {key for key, _ in options}:
        raise SetupInputError("Elija una de las opciones de la lista.")
    return value


def parse_week(values: Mapping[str, str], *, what: str) -> list[dict[str, Any]]:
    """Weekday checkboxes and open/close times -> owner ``{weekday, local_start, local_end}``."""

    windows: list[dict[str, Any]] = []
    for day, name in enumerate(WEEKDAYS):
        if values.get(f"day{day}_open") != "on":
            continue
        try:
            start = time.fromisoformat(values.get(f"day{day}_start", ""))
            end = time.fromisoformat(values.get(f"day{day}_end", ""))
        except ValueError:
            raise SetupInputError(
                f"Escriba las dos horas del {name}, por ejemplo 08:00 y 17:00."
            ) from None
        if start >= end:
            raise SetupInputError(
                f"El {name}, la hora de cierre debe ser después de la hora de apertura."
            )
        windows.append(
            {
                "weekday": day,
                "local_start": start.strftime("%H:%M"),
                "local_end": end.strftime("%H:%M"),
            }
        )
    if not windows:
        raise SetupInputError(f"Marque al menos un día {what}.")
    return windows


def week_rows(values: Mapping[str, str] | None, windows: object = None) -> list[dict[str, Any]]:
    """Rows for the weekday editor: submitted values, else current windows, else Mon-Fri 8-5."""

    current: dict[int, tuple[str, str]] = {}
    for raw in as_list(windows):
        window = as_mapping(raw)
        day = window.get("weekday")
        if isinstance(day, int) and 0 <= day <= 6 and day not in current:
            current[day] = (str(window.get("local_start"))[:5], str(window.get("local_end"))[:5])
    if values is None and not current:
        current = dict(_DEFAULT_WEEK)
    rows: list[dict[str, Any]] = []
    for day, name in enumerate(WEEKDAYS):
        if values is not None:
            rows.append(
                {
                    "day": day,
                    "name": name.capitalize(),
                    "open": values.get(f"day{day}_open") == "on",
                    "start": values.get(f"day{day}_start", "08:00"),
                    "end": values.get(f"day{day}_end", "17:00"),
                }
            )
        else:
            start, end = current.get(day, ("08:00", "17:00" if day < 5 else "12:00"))
            rows.append(
                {
                    "day": day,
                    "name": name.capitalize(),
                    "open": day in current,
                    "start": start,
                    "end": end,
                }
            )
    return rows


def same_windows(current: object, wanted: list[dict[str, Any]]) -> bool:
    def normal(windows: Iterable[Any]) -> set[tuple[int, str, str]]:
        found: set[tuple[int, str, str]] = set()
        for raw in windows:
            window = as_mapping(raw)
            if window.get("valid_from") or window.get("valid_until"):
                return {(-1, "", "")}
            found.add(
                (
                    int(window.get("weekday", -1)),
                    str(window.get("local_start"))[:5],
                    str(window.get("local_end"))[:5],
                )
            )
        return found

    return normal(as_list(current)) == normal(wanted)


def describe_week(windows: object) -> str:
    """'Lunes a viernes 08:00-17:00; sábado 08:00-12:00' from owner windows."""

    by_day: dict[int, str] = {}
    for raw in as_list(windows):
        window = as_mapping(raw)
        day = window.get("weekday")
        if isinstance(day, int) and 0 <= day <= 6:
            span = f"{str(window.get('local_start'))[:5]}–{str(window.get('local_end'))[:5]}"
            by_day[day] = f"{by_day[day]}, {span}" if day in by_day else span
    parts: list[str] = []
    day = 0
    while day < 7:
        if day not in by_day:
            day += 1
            continue
        last = day
        while last + 1 < 7 and by_day.get(last + 1) == by_day[day]:
            last += 1
        days = WEEKDAYS[day] if last == day else f"{WEEKDAYS[day]} a {WEEKDAYS[last]}"
        parts.append(f"{days} {by_day[day]}")
        day = last + 1
    summary = "; ".join(parts)
    return summary[:1].upper() + summary[1:] if summary else "Todavía no tiene horario"


def parse_amount(values: Mapping[str, str]) -> str:
    text = values.get("price", "").strip().replace(",", "").removeprefix("RD$").removeprefix("$")
    if not text:
        raise SetupInputError("Escriba un precio. Use 0 si el servicio es gratis.")
    if not _AMOUNT.fullmatch(text):
        raise SetupInputError("Escriba el precio en números, por ejemplo 1500 o 1500.50.")
    try:
        return str(Decimal(text))
    except InvalidOperation:
        raise SetupInputError("Escriba el precio en números, por ejemplo 1500.") from None


def phone_number(value: str) -> str:
    """A typed phone number in the international form the owner accepts.

    Local Dominican/North American numbers (809, 829, 849 and other 10-digit
    NANP numbers) get the +1 country code; anything else must already carry
    its country code. The owner still validates the result.
    """

    digits = "".join(char for char in value if char.isdigit())
    if value.strip().startswith("+") and 8 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    raise SetupInputError(
        "Escriba el número de teléfono completo, por ejemplo 809 555 0123, o incluya el "
        "código del país, por ejemplo +34 600 123 456."
    )


def contacts(values: Mapping[str, str], fields: Iterable[str]) -> list[dict[str, str]]:
    """Phone/WhatsApp/email fields -> owner ``contacts[{channel, value}]``; blanks skipped."""

    found: list[dict[str, str]] = []
    for channel in fields:
        value = values.get(channel, "").strip()
        if not value:
            continue
        if channel == "email" and not _EMAIL.fullmatch(value):
            raise SetupInputError("Escriba el correo electrónico así: nombre@ejemplo.com.")
        if channel != "email":
            value = phone_number(value)
        found.append({"channel": channel, "value": value[:256]})
    return found


def contact_values(entries: object) -> dict[str, str]:
    """Current owner contacts -> ``{channel: value}`` for prefilling a form."""

    current: dict[str, str] = {}
    for raw in as_list(entries):
        entry = as_mapping(raw)
        channel = entry.get("channel")
        value = entry.get("value") or entry.get("normalized_value")
        if isinstance(channel, str) and isinstance(value, str) and channel not in current:
            current[channel] = value
    return current


def owner_message(payload: object) -> str:
    """The owner's own explanation from an error envelope or validation detail."""

    body = as_mapping(payload)
    error = as_mapping(body.get("error"))
    if isinstance(error.get("message"), str) and error["message"]:
        return str(error["message"])
    for raw in as_list(body.get("detail")):
        detail = as_mapping(raw)
        if isinstance(detail.get("msg"), str):
            return str(detail["msg"]).removeprefix("Value error, ")
    if isinstance(body.get("detail"), str):
        return str(body["detail"])
    return ""


def explain_failure(status: int, payload: object, *, action: str) -> tuple[str, bool]:
    """Plain words for an owner refusal, and whether the step is blocked by permissions."""

    if status == 403:
        return (
            f"Su negocio todavía no tiene permiso para {action}. Esos permisos los da la "
            "plataforma, así que el administrador de la plataforma debe actualizarlos. Puede "
            "saltar este paso y volver cuando eso esté hecho.",
            True,
        )
    if status == 409:
        return (
            "Alguien cambió esto al mismo tiempo. Recargue la página para ver los datos "
            "más recientes y vuelva a intentarlo.",
            False,
        )
    if status in {400, 404, 422}:
        detail = owner_message(payload)
        suffix = f" El sistema del negocio respondió: {detail}." if detail else ""
        return (
            "Algunos datos no fueron aceptados. Revise el formulario y vuelva a intentarlo."
            f"{suffix}",
            False,
        )
    if status == 429:
        return "Demasiados cambios en poco tiempo. Espere un minuto y vuelva a intentarlo.", False
    return (
        "El sistema del negocio no respondió. Vuelva a intentarlo en un momento; lo que ya "
        "se guardó no se duplicará.",
        False,
    )


_READINESS_ACTIONS: dict[str, tuple[str, str]] = {
    "business_party_missing": (
        "Faltan los datos del negocio. "
        "Pídale al administrador de la plataforma que termine de crearlos.",
        "",
    ),
    "location_missing": ("Agregue la sede donde atiende a sus pacientes.", "location"),
    "no_bookable_offering": ("Agregue al menos un servicio con su precio.", "services"),
    "no_resource_supply": (
        "Agregue un médico o consultorio que ofrezca sus servicios.",
        "providers",
    ),
    "service_queue_missing": (
        "Opcional: agregue una fila de espera si llegan pacientes sin cita.",
        "queue",
    ),
    "channel_purpose_disabled": (
        "Los mensajes a pacientes están desactivados. Actívelos en Configuración avanzada.",
        "advanced",
    ),
    "controller_policy_upgrade_required": (
        "Los permisos de su negocio necesitan una actualización "
        "del administrador de la plataforma.",
        "",
    ),
}
_READINESS_LABELS = {
    "business_party": "Datos del negocio",
    "locations": "Sede",
    "appointments": "Citas",
    "walk_in_queue": "Fila de espera sin cita",
    "communications": "Mensajes a pacientes",
    "identity": "Inicio de sesión del dueño",
    "tenant_control": "Permisos del dueño",
    "staff_administration": "Administración del equipo",
    "recovery": "Recuperación de la cuenta",
}


def readiness_rows(payload: object) -> list[dict[str, Any]]:
    """Owner readiness sections in plain words, each blocker turned into a next action."""

    rows: list[dict[str, Any]] = []
    for key, value in as_mapping(payload).items():
        section = as_mapping(value)
        status = section.get("status")
        if status not in {"ready", "blocked", "unknown"}:
            continue
        actions: list[dict[str, str]] = []
        for raw in as_list(section.get("blockers")):
            code = str(as_mapping(raw).get("code") or "")
            text, step = _READINESS_ACTIONS.get(
                code, ("Pídale al administrador de la plataforma que revise esto.", "")
            )
            actions.append({"text": text, "step": step})
        rows.append(
            {
                "key": key,
                "label": _READINESS_LABELS.get(key, key.replace("_", " ").capitalize()),
                "status": status,
                "actions": actions,
            }
        )
    return rows


__all__ = [
    "COUNTRIES",
    "CURRENCIES",
    "DEFAULT_COUNTRY",
    "DEFAULT_CURRENCY",
    "DEFAULT_LOCALE",
    "DEFAULT_TIMEZONE",
    "DURATIONS",
    "LOCALES",
    "MANAGE_PROFILE_SCOPE",
    "PROVIDER_KINDS",
    "PROVINCES",
    "TIMEZONES",
    "MONTHS",
    "WEEKDAYS",
    "long_date",
    "zone_label",
    "SetupInputError",
    "choice",
    "choose_key",
    "contact_values",
    "contacts",
    "describe_week",
    "explain_failure",
    "named",
    "optional_text",
    "owner_message",
    "parse_amount",
    "parse_week",
    "readiness_rows",
    "required_text",
    "same_windows",
    "slugify",
    "valid_intent",
    "week_rows",
]


_CURRENCY_SYMBOLS = {"DOP": "RD$", "USD": "US$"}


def money_label(amount: object, currency: object) -> str:
    """A price as the front desk says it: ``RD$ 1,500.00``, ``US$ 20.00``."""

    try:
        value = Decimal(str(amount))
    except InvalidOperation:
        return ""
    if not value.is_finite():
        return ""
    code = str(currency or "").upper()
    text = f"{value.quantize(Decimal('0.01')):,}"
    symbol = _CURRENCY_SYMBOLS.get(code)
    return f"{symbol} {text}" if symbol else f"{text} {code}".strip()
