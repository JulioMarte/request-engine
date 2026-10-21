"""Guided "Set up your clinic" flow, projected onto existing owner operations.

The flow is a sequence of plain forms. Each form is translated into the exact
body of an owner operation resolved from the live runtime catalog by
operationId, and sent with an ``Idempotency-Key`` derived from one browser form
intent (``clinic-setup:<intent>:<part>``). Nothing here decides permissions,
uniqueness or validity: every command still runs the owner's capability,
Party-authority and schema checks, and a refusal is explained in plain words.

The represented business Party is never typed by a person. It is read from the
owner's self-authority snapshot (``authority_read_self``): the Party the signed-in
owner represents with ``operations.manage_profile`` scope. Commands carry it as
``authority_party_id``; the owner still verifies that representation itself.

Steps are resumable and converge instead of duplicating: before creating, the
current owner inventory is read, and an item with the same generated key and the
same name is treated as the one being submitted again. Revisioned replacements
(location hours) are skipped when the owner already holds the requested value.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

from request_engine.entrypoints.http.admin_console import clinic_setup as forms
from request_engine.entrypoints.http.admin_console.catalog import AdminOperation
from request_engine.entrypoints.http.admin_console.json_types import as_list, as_mapping
from request_engine.entrypoints.http.admin_console.routes_tenant_workspace import (
    business_zone,
    runtime_operations,
    workspace_unavailable,
)
from request_engine.entrypoints.http.admin_console.session import AdminSession
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

# Owner operations this flow reads or runs. Discoverability only: schemas,
# capabilities and authority stay on each owner operation.
CLINIC_SETUP_OPERATION_IDS = frozenset(
    {
        "authority_read_self",
        "business_get_info",
        "tenancy_organization_profile_update",
        "tenancy_organization_contacts_replace",
        "catalog_location_configuration_list",
        "catalog_location_configuration_read",
        "catalog_location_create",
        "catalog_location_hours_replace",
        "catalog_location_contacts_update",
        "catalog_resource_capabilities_list",
        "catalog_manage_resource_capabilities",
        "catalog_offering_configuration_list",
        "catalog_offering_version_configuration_read",
        "catalog_manage_offerings",
        "catalog_offering_booking_terms_configure",
        "catalog_get_offering_details",
        "booking_resource_list",
        "booking_resource_create",
        "queue_service_queue_configuration_list",
        "queue_service_queue_create",
        "onboarding_read",
        "appointments_find_slots",
    }
)


@dataclass(frozen=True)
class _Step:
    key: str
    title: str
    summary: str
    optional: bool = False


STEPS = (
    _Step("clinic", "Your clinic", "Legal name, contact details, time zone and currency.", True),
    _Step("location", "Location and hours", "Where patients come and when you are open."),
    _Step(
        "services", "Services and prices", "What patients can book, how long it takes, its price."
    ),
    _Step("providers", "Doctors and rooms", "Who or what provides each service, and when."),
    _Step("queue", "Walk-in line", "For patients who arrive without an appointment.", True),
    _Step("finish", "Check and finish", "See what is ready and the first free times."),
)
_STEP_KEYS = tuple(step.key for step in STEPS)
_NOTICES = {
    "clinic": "Clinic details saved.",
    "location": "Location and opening hours saved.",
    "service": "Service saved. Add another one, or continue when you are done.",
    "provider": "Saved. Add another doctor or room, or continue when you are done.",
    "provider_exists": "That doctor or room was already added, so nothing was changed.",
    "service_exists": "That service is already added with that price, so nothing was changed.",
    "service_price_kept": (
        "That service already has a different price. Changing a price isn't available yet, "
        "so nothing was changed."
    ),
    "queue": "Walk-in line created.",
    "queue_exists": "That walk-in line already exists, so nothing was changed.",
}
_PAGE_LIMIT = "100"
_MAX_PAGES = 10
_SLOT_PREVIEW = "6"


@dataclass(frozen=True)
class _Answer:
    status: int
    payload: Any = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass
class _Owner:
    """Calls owner operations for one signed-in person and business."""

    state: AdminConsoleState
    organization_id: str
    bearer: str
    ops: dict[str, AdminOperation | None]

    async def call(
        self,
        operation_id: str,
        *,
        path: Mapping[str, str] | None = None,
        params: dict[str, str] | None = None,
        body: object | None = None,
        key: str | None = None,
    ) -> _Answer:
        operation = self.ops.get(operation_id)
        if operation is None:
            return _Answer(503, {"error": {"message": "not available on this installation"}})
        route = operation.path_template
        for name, value in (path or {}).items():
            route = route.replace("{" + name + "}", quote(value, safe=""))
        try:
            response = await self.state.runtime_request(
                operation.method.upper(),
                route,
                organization_id=self.organization_id,
                bearer=self.bearer,
                json_body=body,
                params=params,
                extra_headers={"Idempotency-Key": key} if key else None,
            )
        except (httpx.HTTPError, RuntimeError):
            return _Answer(503)
        return _Answer(response.status_code, response.payload)

    async def collect(
        self, operation_id: str, params: dict[str, str], *, cursor: str
    ) -> tuple[list[dict[str, Any]], int]:
        """Every page of an owner inventory read (bounded), following its cursor."""

        items: list[dict[str, Any]] = []
        query = dict(params)
        for _ in range(_MAX_PAGES):
            answer = await self.call(operation_id, params=query)
            if not answer.ok:
                return items, answer.status
            page = as_mapping(answer.payload)
            items.extend(as_mapping(item) for item in as_list(page.get("items")))
            following = page.get("next_cursor")
            if not following:
                break
            query[cursor] = str(following)
        return items, 200


async def represented_business_party(owner: _Owner) -> tuple[str | None, int]:
    """The Party the signed-in owner manages the business profile for, from the owner."""

    params = {"limit": _PAGE_LIMIT}
    for _ in range(_MAX_PAGES):
        answer = await owner.call("authority_read_self", params=params)
        if not answer.ok:
            return None, answer.status
        snapshot = as_mapping(answer.payload)
        for raw in as_list(snapshot.get("representations")):
            item = as_mapping(raw)
            if item.get("scope_key") == forms.MANAGE_PROFILE_SCOPE:
                try:
                    return str(UUID(str(item.get("represented_party_id")))), 200
                except ValueError:
                    continue
        following = snapshot.get("next_after")
        if not following:
            break
        params = {"limit": _PAGE_LIMIT, "after": str(following)}
    return None, 200


async def resolve_business_party(
    state: AdminConsoleState, organization_id: str, bearer: str
) -> str | None:
    ops = await runtime_operations(state, ("authority_read_self",))
    party, _ = await represented_business_party(_Owner(state, organization_id, bearer, ops))
    return party


@dataclass
class _World:
    """What already exists, read from the owner before showing or changing anything."""

    party: str | None = None
    party_status: int = 0
    business: dict[str, Any] = field(default_factory=lambda: {})
    business_status: int = 0
    locations: list[dict[str, Any]] = field(default_factory=lambda: [])
    offerings: list[dict[str, Any]] = field(default_factory=lambda: [])
    resources: list[dict[str, Any]] = field(default_factory=lambda: [])
    queues: list[dict[str, Any]] = field(default_factory=lambda: [])
    statuses: dict[str, int] = field(default_factory=lambda: {})

    @property
    def timezone(self) -> str:
        return str(self.business.get("default_timezone") or forms.DEFAULT_TIMEZONE)

    @property
    def currency(self) -> str:
        return str(self.business.get("default_currency") or forms.DEFAULT_CURRENCY)

    def counts(self) -> dict[str, int]:
        clinic = bool(self.business.get("legal_name") or self.business.get("contacts"))
        return {
            "clinic": int(clinic),
            "location": len(self.locations),
            "services": len(self.offerings),
            "providers": len(self.resources),
            "queue": len(self.queues),
        }


async def _load_world(owner: _Owner) -> _World:
    world = _World()
    world.party, world.party_status = await represented_business_party(owner)
    business = await owner.call("business_get_info")
    world.business_status = business.status
    world.business = as_mapping(business.payload) if business.ok else {}
    if world.party is None:
        return world
    party = {"authority_party_id": world.party, "limit": _PAGE_LIMIT}
    reads = await asyncio.gather(
        owner.collect("catalog_location_configuration_list", party, cursor="after"),
        owner.collect("catalog_offering_configuration_list", party, cursor="after"),
        owner.collect("booking_resource_list", party, cursor="after"),
        owner.collect("queue_service_queue_configuration_list", party, cursor="cursor"),
    )
    (
        (world.locations, locations),
        (world.offerings, offerings),
        (world.resources, resources),
        (world.queues, queues),
    ) = reads
    world.statuses = {
        "location": locations,
        "services": offerings,
        "providers": resources,
        "queue": queues,
    }
    return world


def _default_step(world: _World) -> str:
    counts = world.counts()
    if not (counts["location"] or counts["services"] or counts["providers"]):
        return "clinic"
    return next((key for key in ("location", "services", "providers") if not counts[key]), "finish")


def _setup_path(organization_id: str, step: str = "", done: str = "") -> str:
    query = "&".join(
        part for part in (f"step={step}" if step else "", f"done={done}" if done else "") if part
    )
    return f"/tenants/{organization_id}/setup" + (f"?{query}" if query else "")


@dataclass
class _Problem:
    message: str
    blocked: bool = False
    saved: list[str] = field(default_factory=lambda: [])


def _failure(answer: _Answer, action: str, saved: list[str] | None = None) -> _Problem:
    message, blocked = forms.explain_failure(answer.status, answer.payload, action=action)
    return _Problem(message, blocked, list(saved or []))


async def _service_choices(owner: _Owner, world: _World) -> list[dict[str, str]]:
    """One choice per service: the resource capability its latest version requires."""

    reads = await asyncio.gather(
        *(
            owner.call(
                "catalog_offering_version_configuration_read",
                path={"offering_version_id": str(item.get("offering_version_id"))},
            )
            for item in world.offerings
        )
    )
    choices: list[dict[str, str]] = []
    for offering, answer in zip(world.offerings, reads, strict=True):
        requirements = as_list(as_mapping(answer.payload).get("requirements")) if answer.ok else []
        if requirements and offering.get("active") is not False:
            choices.append(
                {
                    "capability_id": str(as_mapping(requirements[0]).get("capability_id")),
                    "name": str(offering.get("display_name")),
                }
            )
    return choices


async def _slot_preview(owner: _Owner, world: _World) -> dict[str, Any]:
    zone, _ = business_zone(world.business)
    offering = next(
        (
            item
            for item in world.offerings
            if item.get("bookable") and item.get("active") is not False
        ),
        None,
    )
    if offering is None:
        return {"status": 0, "service": "", "slots": []}
    now = datetime.now(UTC)
    answer = await owner.call(
        "appointments_find_slots",
        params={
            "offering_version_id": str(offering.get("offering_version_id")),
            "window_start": now.isoformat(),
            "window_end": (now + timedelta(days=7)).isoformat(),
            "limit": _SLOT_PREVIEW,
        },
    )
    slots: list[str] = []
    for raw in as_list(answer.payload) if answer.ok else []:
        try:
            start = datetime.fromisoformat(str(as_mapping(raw).get("start_at"))).astimezone(zone)
        except ValueError:
            continue
        slots.append(f"{forms.WEEKDAYS[start.weekday()]} {start.day} {start:%B}, {start:%H:%M}")
    return {"status": answer.status, "service": str(offering.get("display_name")), "slots": slots}


def install_clinic_setup_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _owner(organization_id: UUID, session: AdminSession) -> _Owner:
        ops = await runtime_operations(state, tuple(sorted(CLINIC_SETUP_OPERATION_IDS)))
        return _Owner(state, str(organization_id), session.access_token, ops)

    async def _render(
        request: Request,
        owner: _Owner,
        world: _World,
        step: str,
        *,
        values: Mapping[str, str] | None = None,
        selected: tuple[str, ...] = (),
        problem: _Problem | None = None,
        notice: str = "",
        status_code: int = 200,
    ) -> Response:
        org = owner.organization_id
        counts = world.counts()
        extra: dict[str, Any] = {}
        if step == "providers":
            extra["services"] = await _service_choices(owner, world)
            names = {choice["capability_id"]: choice["name"] for choice in extra["services"]}
            extra["provider_rows"] = [
                {
                    "name": item.get("display_name"),
                    "services": [
                        names[str(cid)]
                        for cid in as_list(item.get("capability_ids"))
                        if str(cid) in names
                    ],
                    "active": item.get("active") is not False,
                }
                for item in world.resources
            ]
        if step == "finish":
            readiness, preview = await asyncio.gather(
                owner.call("onboarding_read"), _slot_preview(owner, world)
            )
            extra["readiness_status"] = readiness.status
            extra["readiness"] = forms.readiness_rows(readiness.payload) if readiness.ok else []
            extra["preview"] = preview
        business_locations = {
            str(as_mapping(item).get("id")): as_mapping(item)
            for item in as_list(world.business.get("locations"))
        }
        first_hours = next(
            (item.get("operational_hours") for item in business_locations.values()), None
        )
        position = _STEP_KEYS.index(step)
        return state.templates.TemplateResponse(
            request,
            "resources/clinic_setup.html",
            state.context(
                request,
                organization_id=org,
                step=step,
                step_number=position + 1,
                step_count=len(STEPS),
                current=STEPS[position],
                next_step=STEPS[position + 1].key if position + 1 < len(STEPS) else "",
                steps=[
                    {
                        "key": item.key,
                        "title": item.title,
                        "summary": item.summary,
                        "optional": item.optional,
                        "count": counts.get(item.key, 0),
                        "current": item.key == step,
                        "href": _setup_path(org, item.key),
                    }
                    for item in STEPS
                ],
                world=world,
                business_name=world.business.get("display_name") or "your clinic",
                business_contacts=forms.contact_values(world.business.get("contacts")),
                location_rows=[
                    {
                        "name": item.get("display_name"),
                        "address": ", ".join(
                            str(part)
                            for part in (
                                item.get("address_line1"),
                                item.get("locality"),
                                item.get("administrative_area"),
                            )
                            if part
                        ),
                        "hours": forms.describe_week(
                            business_locations.get(str(item.get("location_id")), {}).get(
                                "operational_hours"
                            )
                        ),
                        "active": item.get("active") is not False,
                    }
                    for item in world.locations
                ],
                values=values or {},
                selected=selected,
                week=forms.week_rows(
                    values if values and "day0_start" in values else None,
                    first_hours if step == "providers" else None,
                ),
                problem=problem,
                notice=notice,
                intent_id=token_urlsafe(16),
                timezones=forms.TIMEZONES,
                currencies=forms.CURRENCIES,
                locales=forms.LOCALES,
                countries=forms.COUNTRIES,
                provinces=forms.PROVINCES,
                durations=forms.DURATIONS,
                provider_kinds=forms.PROVIDER_KINDS,
                defaults={
                    "timezone": world.timezone,
                    "currency": world.currency,
                    "locale": str(world.business.get("default_locale") or forms.DEFAULT_LOCALE),
                    "country": forms.DEFAULT_COUNTRY,
                },
                **extra,
            ),
            status_code=status_code,
        )

    def _gate(request: Request, organization_id: UUID, step: str = "") -> AdminSession | Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse(
                f"/login?next={_setup_path(str(organization_id), step)}", status_code=303
            )
        if state.runtime is None:
            return workspace_unavailable(state, request, "Clinic setup unavailable")
        return session

    def _relogin(request: Request) -> Response:
        response = RedirectResponse("/login", status_code=303)
        state.clear_session(response, request)
        return response

    async def page(
        request: Request, organization_id: UUID, step: str = "", done: str = ""
    ) -> Response:
        session = _gate(request, organization_id, step)
        if isinstance(session, Response):
            return session
        owner = await _owner(organization_id, session)
        world = await _load_world(owner)
        if 401 in {world.party_status, world.business_status}:
            return _relogin(request)
        chosen = step if step in _STEP_KEYS else _default_step(world)
        return await _render(request, owner, world, chosen, notice=_NOTICES.get(done, ""))

    async def submit(request: Request, organization_id: UUID, step: str) -> Response:
        if step not in _STEP_KEYS or step == "finish":
            return Response("Unknown setup step", status_code=404)
        session = _gate(request, organization_id, step)
        if isinstance(session, Response):
            return session
        form = await request.form()
        values = {key: str(value) for key, value in form.items()}
        selected = tuple(str(value) for value in form.getlist("capability_id"))
        if not state.csrf_matches(values.get("csrf_token"), session.csrf_token):
            return RedirectResponse(_setup_path(str(organization_id), step), status_code=303)
        owner = await _owner(organization_id, session)
        world = await _load_world(owner)
        if 401 in {world.party_status, world.business_status}:
            return _relogin(request)

        async def again(problem: _Problem, status_code: int) -> Response:
            return await _render(
                request, owner, world, step, values=values, selected=selected,
                problem=problem, status_code=status_code,
            )  # fmt: skip

        intent = values.get("_intent_id", "")
        if not forms.valid_intent(intent):
            return await again(_Problem("This form expired. Reload the page and try again."), 422)
        if world.party is None:
            return await again(_Problem(_NO_PARTY, blocked=True), 409)
        handler = _HANDLERS[step]
        try:
            outcome = await handler(owner, world, values, selected, f"clinic-setup:{intent}")
        except forms.SetupInputError as error:
            return await again(_Problem(str(error)), 422)
        if isinstance(outcome, tuple):
            problem, status_code = outcome
            if status_code == 401:
                return _relogin(request)
            return await again(problem, status_code if 400 <= status_code < 600 else 502)
        return RedirectResponse(outcome, status_code=303)

    app.add_api_route("/tenants/{organization_id}/setup", page, methods=["GET"])
    app.add_api_route("/tenants/{organization_id}/setup/{step}", submit, methods=["POST"])


_NO_PARTY = (
    "Your sign-in does not manage this business's profile, so setup cannot continue. "
    "Ask the platform administrator to check that your account is the business owner."
)
_Outcome = str | tuple[_Problem, int]


async def _save_clinic(
    owner: _Owner, world: _World, values: Mapping[str, str], _: tuple[str, ...], key: str
) -> _Outcome:
    profile: dict[str, Any] = {
        "authority_party_id": world.party,
        "default_timezone": forms.choice(values, "timezone", forms.TIMEZONES, world.timezone),
        "default_currency": forms.choice(values, "currency", forms.CURRENCIES, world.currency),
        "default_locale": forms.choice(values, "locale", forms.LOCALES, forms.DEFAULT_LOCALE),
    }
    legal_name = forms.optional_text(values, "legal_name")
    if legal_name:
        profile["legal_name"] = legal_name
    wanted = forms.contacts(values, ("phone", "whatsapp", "email"))
    answer = await owner.call(
        "tenancy_organization_profile_update", body=profile, key=f"{key}:profile"
    )
    if not answer.ok:
        return _failure(answer, "change its profile"), answer.status
    current = forms.contact_values(world.business.get("contacts"))
    if {item["channel"]: item["value"] for item in wanted} != current:
        answer = await owner.call(
            "tenancy_organization_contacts_replace",
            body={"authority_party_id": world.party, "contacts": wanted},
            key=f"{key}:contacts",
        )
        if not answer.ok:
            problem = _failure(
                answer, "change its contact details", ["Legal name, time zone and currency"]
            )
            return problem, answer.status
    return _setup_path(owner.organization_id, "location", "clinic")


async def _save_location(
    owner: _Owner, world: _World, values: Mapping[str, str], _: tuple[str, ...], key: str
) -> _Outcome:
    name = forms.required_text(
        values, "display_name", "Enter the location's name, for example Sede Gazcue."
    )
    windows = forms.parse_week(values, what="the location is open")
    wanted_contacts = forms.contacts(values, ("phone", "whatsapp"))
    location_key, existing = forms.choose_key(
        forms.slugify(name, fallback="location"),
        world.locations,
        key_field="location_key",
        display_name=name,
    )
    party = str(world.party)
    if existing is None:
        body: dict[str, Any] = {
            "authority_party_id": party,
            "location_key": location_key,
            "display_name": name,
            "timezone": world.timezone,
            "country_code": forms.choice(
                values, "country_code", forms.COUNTRIES, forms.DEFAULT_COUNTRY
            ),
        }
        for field_name in ("address_line1", "address_line2", "locality", "administrative_area"):
            text = forms.optional_text(values, field_name)
            if text:
                body[field_name] = text
        created = await owner.call("catalog_location_create", body=body, key=f"{key}:location")
        if not created.ok:
            return _failure(created, "add locations"), created.status
        location = as_mapping(created.payload)
        hours: object = []
        current_contacts: object = []
    else:
        detail = await owner.call(
            "catalog_location_configuration_read",
            path={"location_id": str(existing.get("location_id"))},
            params={"authority_party_id": party},
        )
        if not detail.ok:
            return _failure(detail, "read its locations"), detail.status
        location = as_mapping(detail.payload)
        hours, current_contacts = location.get("hours_windows"), location.get("public_contacts")
    location_id, revision = str(location.get("location_id")), location.get("operational_revision")
    saved = [f"The location “{name}”"]
    if not forms.same_windows(hours, windows):
        answer = await owner.call(
            "catalog_location_hours_replace",
            path={"location_id": location_id},
            body={
                "authority_party_id": party,
                "expected_operational_revision": revision,
                "windows": windows,
            },
            key=f"{key}:hours:{revision}",
        )
        if not answer.ok:
            return _failure(answer, "change opening hours", saved), answer.status
        saved.append("its opening hours")
    if wanted_contacts and {
        c["channel"]: c["value"] for c in wanted_contacts
    } != forms.contact_values(current_contacts):
        answer = await owner.call(
            "catalog_location_contacts_update",
            path={"location_id": location_id},
            body={"authority_party_id": party, "contacts": wanted_contacts},
            key=f"{key}:location-contacts",
        )
        if not answer.ok:
            return _failure(answer, "change location phone numbers", saved), answer.status
    return _setup_path(owner.organization_id, "services", "location")


async def _save_service(
    owner: _Owner, world: _World, values: Mapping[str, str], _: tuple[str, ...], key: str
) -> _Outcome:
    name = forms.required_text(
        values, "display_name", "Enter the service's name, for example General consultation."
    )
    duration = int(
        forms.choice(values, "duration_minutes", ((str(d), "") for d in forms.DURATIONS), "30")
    )
    amount = forms.parse_amount(values)
    currency = forms.choice(values, "currency", forms.CURRENCIES, world.currency)
    party = str(world.party)
    offering_key, existing = forms.choose_key(
        forms.slugify(name, fallback="service"),
        world.offerings,
        key_field="offering_key",
        display_name=name,
    )
    saved: list[str] = []
    if existing is not None:
        version_id = str(existing.get("offering_version_id"))
        kept = await _existing_price_outcome(owner, offering_key, version_id, amount, currency)
        if kept is not None:
            return kept
    else:
        capability_key = f"provides-{offering_key}"
        capabilities, status = await owner.collect(
            "catalog_resource_capabilities_list", {"limit": "200"}, cursor="cursor"
        )
        if status != 200:
            return _failure(_Answer(status), "read its services"), status
        capability = next(
            (c for c in capabilities if c.get("capability_key") == capability_key), None
        )
        if capability is None:
            created = await owner.call(
                "catalog_manage_resource_capabilities",
                body={
                    "authority_party_id": party,
                    "capability_key": capability_key,
                    "display_name": f"Provides {name}"[:200],
                },
                key=f"{key}:capability",
            )
            if not created.ok:
                return _failure(created, "add services"), created.status
            capability = as_mapping(created.payload)
        offering = await owner.call(
            "catalog_manage_offerings",
            body={
                "authority_party_id": party,
                "offering_key": offering_key,
                "display_name": name,
                "duration_minutes": duration,
                "slot_step_minutes": duration if duration <= 60 else 30,
                "requirements": [
                    {"capability_id": str(capability.get("capability_id")), "quantity": 1}
                ],
            },
            key=f"{key}:offering",
        )
        if not offering.ok:
            return _failure(offering, "add services"), offering.status
        version_id = str(as_mapping(offering.payload).get("offering_version_id"))
        saved.append(f"The service “{name}”")
    terms = await owner.call(
        "catalog_offering_booking_terms_configure",
        path={"offering_version_id": version_id},
        body={"authority_party_id": party, "amount": amount, "currency": currency},
        key=f"{key}:terms:{version_id}",
    )
    if not terms.ok:
        return _failure(terms, "set prices", saved), terms.status
    return _setup_path(owner.organization_id, "services", "service")


async def _existing_price_outcome(
    owner: _Owner, offering_key: str, version_id: str, amount: str, currency: str
) -> _Outcome | None:
    """A resubmitted service whose price is already set is never priced twice.

    Base booking terms are set once per offering version (the owner answers 409
    otherwise), so the owner's current price decides what to tell the person.
    """

    current = await owner.call("catalog_get_offering_details", path={"offering_key": offering_key})
    latest = as_mapping(as_mapping(current.payload).get("latest_version")) if current.ok else {}
    if str(latest.get("id")) != version_id or latest.get("amount") is None:
        return None
    same = Decimal(str(latest.get("amount"))) == Decimal(amount) and (
        latest.get("currency") == currency
    )
    done = "service_exists" if same else "service_price_kept"
    return _setup_path(owner.organization_id, "services", done)


def _known_location(world: _World, values: Mapping[str, str]) -> str:
    location_id = values.get("location_id", "")
    if location_id not in {str(item.get("location_id")) for item in world.locations}:
        raise forms.SetupInputError(
            "Choose the location. Add one in the location step first if the list is empty."
        )
    return location_id


async def _save_provider(
    owner: _Owner, world: _World, values: Mapping[str, str], selected: tuple[str, ...], key: str
) -> _Outcome:
    name = forms.required_text(
        values, "display_name", "Enter a name, for example Dra. Ana Pérez or Consultorio 2."
    )
    kind = forms.choice(values, "kind", forms.PROVIDER_KINDS, "doctor")
    location_id = _known_location(world, values)
    offered = {choice["capability_id"] for choice in await _service_choices(owner, world)}
    if offered and not selected:
        raise forms.SetupInputError("Tick at least one service they provide.")
    if not set(selected) <= offered:
        raise forms.SetupInputError("Choose services from the list. Reload the page if it changed.")
    windows = forms.parse_week(values, what="they work")
    resource_key, existing = forms.choose_key(
        f"{kind}-{forms.slugify(name, fallback='provider')}",
        world.resources,
        key_field="resource_key",
        display_name=name,
    )
    if existing is not None:
        return _setup_path(owner.organization_id, "providers", "provider_exists")
    created = await owner.call(
        "booking_resource_create",
        body={
            "authority_party_id": world.party,
            "location_id": location_id,
            "resource_key": resource_key,
            "display_name": name,
            "capacity_model": "exclusive",
            "capability_ids": list(dict.fromkeys(selected)),
            "weekly_availability": windows,
        },
        key=f"{key}:resource",
    )
    if not created.ok:
        return _failure(created, "add doctors or rooms"), created.status
    return _setup_path(owner.organization_id, "providers", "provider")


async def _save_queue(
    owner: _Owner, world: _World, values: Mapping[str, str], _: tuple[str, ...], key: str
) -> _Outcome:
    name = forms.required_text(
        values, "display_name", "Enter a name for the line, for example Walk-ins."
    )
    location_id = _known_location(world, values)
    offering_id = values.get("offering_id", "")
    if offering_id and offering_id not in {
        str(item.get("offering_id")) for item in world.offerings
    }:
        raise forms.SetupInputError("Choose a service from the list, or leave it as any service.")
    queue_key, existing = forms.choose_key(
        forms.slugify(name, fallback="walk-ins"),
        world.queues,
        key_field="queue_key",
        display_name=name,
    )
    if existing is not None:
        return _setup_path(owner.organization_id, "finish", "queue_exists")
    body: dict[str, Any] = {
        "authority_party_id": world.party,
        "location_id": location_id,
        "queue_key": queue_key,
        "display_name": name,
    }
    if offering_id:
        body["offering_id"] = offering_id
    created = await owner.call("queue_service_queue_create", body=body, key=f"{key}:queue")
    if not created.ok:
        return _failure(created, "create walk-in lines"), created.status
    return _setup_path(owner.organization_id, "finish", "queue")


_HANDLERS = {
    "clinic": _save_clinic,
    "location": _save_location,
    "services": _save_service,
    "providers": _save_provider,
    "queue": _save_queue,
}

__all__ = [
    "CLINIC_SETUP_OPERATION_IDS",
    "STEPS",
    "install_clinic_setup_routes",
    "represented_business_party",
    "resolve_business_party",
]
