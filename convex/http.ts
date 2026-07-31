import { ConvexError } from "convex/values"
import { httpRouter } from "convex/server"
import type { Id } from "./_generated/dataModel"
import { httpAction } from "./_generated/server"
import type { ActionCtx } from "./_generated/server"
import { internal } from "./_generated/api"
import { openApiDocument } from "./openapi"

declare const process: { env: Record<string, string | undefined> }

type JsonObject = Record<string, unknown>
type AuthInfo = {
  keyId: Id<"apiKeys">
  principalId: Id<"principals">
  principalType: "platform" | "organization" | "agent" | "integration" | "human"
  principalName: string
  organizationId?: Id<"organizations">
  organizationPublicId?: string
  scopes: string[]
}

const headers = { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*", "access-control-allow-headers": "Authorization, Content-Type, Idempotency-Key, X-Bootstrap-Secret, X-Request-Engine-Signature, X-Request-Engine-Timestamp", "access-control-allow-methods": "GET, POST, OPTIONS" }

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers })
}

function text(value: unknown, field: string, optional = false) {
  if (optional && value === undefined) return undefined
  if (typeof value !== "string" || (!optional && !value.trim())) throw new ConvexError({ code: "INVALID_INPUT", message: `${field} must be a non-empty string`, details: { field } })
  return value
}

function number(value: unknown, field: string, fallback?: number) {
  if (value === undefined && fallback !== undefined) return fallback
  if (typeof value !== "number" || !Number.isFinite(value)) throw new ConvexError({ code: "INVALID_INPUT", message: `${field} must be a number`, details: { field } })
  return value
}

function boolean(value: unknown, field: string, fallback?: boolean) {
  if (value === undefined && fallback !== undefined) return fallback
  if (typeof value !== "boolean") throw new ConvexError({ code: "INVALID_INPUT", message: `${field} must be a boolean`, details: { field } })
  return value
}

function strings(value: unknown, field: string, fallback: string[] = []) {
  if (value === undefined) return fallback
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) throw new ConvexError({ code: "INVALID_INPUT", message: `${field} must be an array of strings`, details: { field } })
  return value as string[]
}

async function body(request: Request): Promise<JsonObject> {
  const parsed: unknown = await request.json()
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new ConvexError({ code: "INVALID_INPUT", message: "JSON body must be an object", details: {} })
  return parsed as JsonObject
}

async function sha256(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value))
  return Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("")
}

function base64(bytes: Uint8Array) {
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

async function protectSensitive(value: string) {
  const encryptionSecret = process.env.PII_ENCRYPTION_KEY
  const blindIndexSecret = process.env.PII_BLIND_INDEX_KEY
  if (!encryptionSecret || !blindIndexSecret) throw new ConvexError({ code: "CONFIGURATION_ERROR", message: "PII encryption secrets are not configured", details: {} })
  const encryptionKey = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(encryptionSecret))
  const key = await crypto.subtle.importKey("raw", encryptionKey, "AES-GCM", false, ["encrypt"])
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const normalized = value.normalize("NFKC").replace(/[\s-]/g, "").toLocaleUpperCase()
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, new TextEncoder().encode(normalized))
  const blindKey = await crypto.subtle.importKey("raw", new TextEncoder().encode(blindIndexSecret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
  const blind = await crypto.subtle.sign("HMAC", blindKey, new TextEncoder().encode(normalized))
  const maskedValue = normalized.length <= 4 ? "•".repeat(normalized.length) : `${"•".repeat(Math.min(8, normalized.length - 4))}${normalized.slice(-4)}`
  return { encryptedValue: `${base64(iv)}.${base64(new Uint8Array(cipher))}`, blindHash: base64(new Uint8Array(blind)), maskedValue, encryptionKeyVersion: 1 }
}

function allows(scopes: string[], required: string) {
  return scopes.includes("*") || scopes.includes(required) || scopes.includes(`${required.split(":")[0]}:*`)
}

async function authenticate(ctx: ActionCtx, request: Request, requiredScope: string, requestedOrganizationId?: string): Promise<AuthInfo> {
  const authorization = request.headers.get("authorization")
  if (!authorization?.startsWith("Bearer ")) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "Bearer API key required", details: {} })
  const secretHash = await sha256(authorization.slice(7))
  const auth: AuthInfo | null = await ctx.runQuery(internal.v1AgentAuth.resolve, { secretHash })
  if (!auth) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "API key is invalid, expired or revoked", details: {} })
  if (!allows(auth.scopes, requiredScope)) throw new ConvexError({ code: "INSUFFICIENT_SCOPE", message: `Scope ${requiredScope} is required`, details: { requiredScope } })
  if (requestedOrganizationId && auth.principalType !== "platform" && auth.organizationPublicId !== requestedOrganizationId) throw new ConvexError({ code: "TENANT_SCOPE_VIOLATION", message: "API key cannot access this organization", details: {} })
  await ctx.runMutation(internal.v1AgentAuth.touch, { keyId: auth.keyId })
  return auth
}

function requireBootstrap(request: Request) {
  const configured = process.env.PLATFORM_BOOTSTRAP_SECRET
  if (!configured || request.headers.get("x-bootstrap-secret") !== configured) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "Valid platform bootstrap secret required", details: {} })
}

async function issueApiKey(ctx: ActionCtx, request: Request) {
  requireBootstrap(request)
  const input = await body(request)
  const secret = `re_${crypto.randomUUID().replaceAll("-", "")}${crypto.randomUUID().replaceAll("-", "")}`
  const prefix = secret.slice(0, 12)
  const stored: { keyId: string, prefix: string } = await ctx.runMutation(internal.v1AgentAuth.store, {
    principalPublicId: text(input.principalId, "principalId")!, prefix, secretHash: await sha256(secret), scopes: strings(input.scopes, "scopes"),
    expiresAt: input.expiresAt ? Date.parse(text(input.expiresAt, "expiresAt")!) : undefined,
  })
  return response({ ...stored, secret, warning: "This secret is shown once. Store it in a secrets manager." }, 201)
}

async function verifyWebhook(request: Request, rawBody: string) {
  const secret = process.env.INTEGRATION_WEBHOOK_SECRET
  const signature = request.headers.get("x-request-engine-signature")
  const timestamp = request.headers.get("x-request-engine-timestamp")
  if (!secret || !signature || !timestamp || Math.abs(Date.now() - Number(timestamp)) > 5 * 60_000) return false
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
  const signed = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${rawBody}`))
  const expected = Array.from(new Uint8Array(signed)).map((byte) => byte.toString(16).padStart(2, "0")).join("")
  const provided = signature.replace(/^sha256=/, "")
  if (provided.length !== expected.length) return false
  let mismatch = 0
  for (let index = 0; index < expected.length; index += 1) mismatch |= expected.charCodeAt(index) ^ provided.charCodeAt(index)
  return mismatch === 0
}

async function post(ctx: ActionCtx, request: Request, path: string): Promise<Response> {
  if (path === "/v1/onboarding/organizations") {
    requireBootstrap(request)
    const input = await body(request)
    const result = await ctx.runMutation(internal.v1Organizations.bootstrap, {
      name: text(input.name, "name")!, legalName: text(input.legalName, "legalName", true), industry: text(input.industry, "industry")!, countryCode: text(input.countryCode, "countryCode")!,
      timezone: text(input.timezone, "timezone")!, locale: text(input.locale, "locale")!, locationName: text(input.locationName, "locationName")!, terminology: text(input.terminology, "terminology")!,
      ownerFullName: text(input.ownerFullName, "ownerFullName")!, ownerEmail: text(input.ownerEmail, "ownerEmail")!, ownerPhoneE164: text(input.ownerPhoneE164, "ownerPhoneE164")!,
    })
    return response(result, 201)
  }
  if (path === "/v1/api-keys") return issueApiKey(ctx, request)
  if (path === "/v1/onboarding/otp/request") {
    requireBootstrap(request)
    const input = await body(request)
    const onboardingId = text(input.onboardingId, "onboardingId")!
    const context = await ctx.runQuery(internal.v1Organizations.onboardingContext, { onboardingPublicId: onboardingId })
    if (!context || !context.phoneAllowed || !context.webhookVerified) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "Onboarding source is not allowed", details: {} })
    const url = process.env.N8N_OTP_WEBHOOK_URL
    const secret = process.env.N8N_OTP_WEBHOOK_SECRET
    if (!url || !secret) throw new ConvexError({ code: "CONFIGURATION_ERROR", message: "OTP delivery adapter is not configured", details: {} })
    const code = String(crypto.getRandomValues(new Uint32Array(1))[0] % 1_000_000).padStart(6, "0")
    const result = await fetch(url, { method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${secret}` }, body: JSON.stringify({ eventType: "onboarding.email_otp", email: context.ownerEmail, code, expiresInMinutes: 10 }) })
    if (!result.ok) throw new ConvexError({ code: "DELIVERY_FAILED", message: "OTP email was not accepted by the delivery adapter", details: { status: result.status } })
    await ctx.runMutation(internal.v1Organizations.storeOtp, { onboardingId: context.id, otpHash: await sha256(`${context.publicId}:${code}`), expiresAt: Date.now() + 10 * 60_000 })
    return response({ accepted: true, destination: context.ownerEmail.replace(/^(.{2}).*(@.*)$/, "$1••••$2"), expiresInSeconds: 600 })
  }
  if (path === "/v1/onboarding/otp/verify") {
    requireBootstrap(request)
    const input = await body(request)
    const onboardingId = text(input.onboardingId, "onboardingId")!
    const code = text(input.code, "code")!
    return response(await ctx.runMutation(internal.v1Organizations.verifyOtp, { onboardingPublicId: onboardingId, otpHash: await sha256(`${onboardingId}:${code}`) }))
  }
  if (path === "/v1/integrations/notification-callback") {
    const raw = await request.text()
    if (!await verifyWebhook(request, raw)) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "Invalid webhook signature or timestamp", details: {} })
    const input = JSON.parse(raw) as JsonObject
    const result = await ctx.runMutation(internal.v1Callbacks.notification, {
      provider: text(input.provider, "provider")!, externalEventId: text(input.externalEventId, "externalEventId")!, organizationPublicId: text(input.organizationId, "organizationId")!, deliveryPublicId: text(input.deliveryId, "deliveryId")!,
      status: text(input.status, "status") as "dispatched" | "delivered" | "failed" | "responded", channel: text(input.channel, "channel") as "whatsapp" | "sms" | "email" | "voice",
      resultCode: text(input.resultCode, "resultCode", true), sipStatus: text(input.sipStatus, "sipStatus", true), intent: text(input.intent, "intent", true) as "confirm" | "cancel" | "reprogram" | "unknown" | undefined, payloadHash: await sha256(raw),
    })
    return response(result)
  }
  if (path === "/v1/integrations/evolution-callback") {
    const raw = await request.text()
    if (!await verifyWebhook(request, raw)) throw new ConvexError({ code: "AUTHENTICATION_REQUIRED", message: "Invalid Evolution webhook signature or timestamp", details: {} })
    const input = JSON.parse(raw) as JsonObject
    const data = (input.data && typeof input.data === "object" ? input.data : {}) as JsonObject
    const instanceName = text(input.instance, "instance", true) ?? text(data.instance, "data.instance")!
    const connectionState = (text(data.state, "data.state", true) ?? text(input.state, "state", true) ?? "connecting") as "open" | "close" | "connecting"
    const qrCode = text(data.qrcode, "data.qrcode", true) ?? text(data.base64, "data.base64", true)
    return response(await ctx.runMutation(internal.v1Provisioning.evolutionConnectionUpdate, { instanceName, externalEventId: text(input.eventId, "eventId", true) ?? await sha256(raw), connectionState, qrCode, payloadHash: await sha256(raw) }))
  }

  const input = await body(request)
  const organizationId = text(input.organizationId, "organizationId")!
  if (path === "/v1/catalog/search") {
    await authenticate(ctx, request, "catalog:read", organizationId)
    return response({ data: await ctx.runQuery(internal.v1Catalog.search, { organizationPublicId: organizationId, query: text(input.query, "query", true) ?? "", bookingMode: text(input.bookingMode, "bookingMode", true) as "fixed_time" | "arrival_window" | "class_session" | undefined, modality: text(input.modality, "modality", true) as "onsite" | "virtual" | "at_customer_location" | "hybrid" | undefined, limit: number(input.limit, "limit", 5) }) })
  }
  if (path === "/v1/services") {
    await authenticate(ctx, request, "catalog:write", organizationId)
    const rawPrice = input.price as JsonObject
    return response(await ctx.runMutation(internal.v1Catalog.createService, {
      organizationPublicId: organizationId, name: text(input.name, "name")!, description: text(input.description, "description")!, synonyms: strings(input.synonyms, "synonyms"),
      bookingMode: text(input.bookingMode, "bookingMode") as "fixed_time" | "arrival_window" | "class_session", modalities: strings(input.modalities, "modalities") as Array<"onsite" | "virtual" | "at_customer_location" | "hybrid">,
      durationMinutes: number(input.durationMinutes, "durationMinutes"), slotIntervalMinutes: number(input.slotIntervalMinutes, "slotIntervalMinutes", 15), bufferBeforeMinutes: number(input.bufferBeforeMinutes, "bufferBeforeMinutes", 0), bufferAfterMinutes: number(input.bufferAfterMinutes, "bufferAfterMinutes", 0), capacity: number(input.capacity, "capacity", 1),
      price: { amountMinor: number(rawPrice?.amountMinor, "price.amountMinor", 0), currency: text(rawPrice?.currency, "price.currency")!, type: text(rawPrice?.type, "price.type") as "fixed" | "from" | "free" | "quote" },
      requiredFields: strings(input.requiredFields, "requiredFields") as Array<"full_name" | "email" | "phone" | "identity_document" | "guardian" | "insurance_coverage">,
      seriesEnrollment: (text(input.seriesEnrollment, "seriesEnrollment", true) ?? "occurrence") as "occurrence" | "series" | "both", autoReleaseUnconfirmed: boolean(input.autoReleaseUnconfirmed, "autoReleaseUnconfirmed", true), neverAutoCancel: boolean(input.neverAutoCancel, "neverAutoCancel", false), waitlistEnabled: boolean(input.waitlistEnabled, "waitlistEnabled", true),
    }), 201)
  }
  if (path === "/v1/resources") {
    await authenticate(ctx, request, "operations:write", organizationId)
    return response(await ctx.runMutation(internal.v1Catalog.createResource, { organizationPublicId: organizationId, locationPublicId: text(input.locationId, "locationId", true), name: text(input.name, "name")!, type: text(input.type, "type") as "staff" | "room" | "equipment" | "vehicle" | "other", capacity: number(input.capacity, "capacity", 1) }), 201)
  }
  if (path === "/v1/locations") {
    await authenticate(ctx, request, "organization:write", organizationId)
    const address = input.address && typeof input.address === "object" ? input.address as JsonObject : undefined
    return response(await ctx.runMutation(internal.v1Catalog.createLocation, { organizationPublicId: organizationId, name: text(input.name, "name")!, terminology: text(input.terminology, "terminology")!, timezone: text(input.timezone, "timezone")!, countryCode: text(input.countryCode, "countryCode")!, subdivisionCode: text(input.subdivisionCode, "subdivisionCode", true), address: address ? { line1: text(address.line1, "address.line1")!, line2: text(address.line2, "address.line2", true), city: text(address.city, "address.city")!, postalCode: text(address.postalCode, "address.postalCode", true) } : undefined }), 201)
  }
  if (path === "/v1/services/resource-requirements") {
    await authenticate(ctx, request, "operations:write", organizationId)
    await ctx.runMutation(internal.v1Catalog.requireResource, { organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, resourceType: text(input.resourceType, "resourceType") as "staff" | "room" | "equipment" | "vehicle" | "other", quantity: number(input.quantity, "quantity", 1), allowedResourcePublicIds: strings(input.allowedResourceIds, "allowedResourceIds"), required: boolean(input.required, "required", true) })
    return response({ created: true }, 201)
  }
  if (path === "/v1/people") {
    await authenticate(ctx, request, "people:write", organizationId)
    return response(await ctx.runMutation(internal.v1People.create, { organizationPublicId: organizationId, fullName: text(input.fullName, "fullName")!, dateOfBirth: text(input.dateOfBirth, "dateOfBirth", true), preferredLocale: text(input.preferredLocale, "preferredLocale", true), email: text(input.email, "email", true), phoneE164: text(input.phoneE164, "phoneE164", true) }), 201)
  }
  if (path === "/v1/people/identifiers") {
    await authenticate(ctx, request, "pii:write", organizationId)
    const protectedValue = await protectSensitive(text(input.value, "value")!)
    return response(await ctx.runMutation(internal.v1People.storeIdentifier, { organizationPublicId: organizationId, personPublicId: text(input.personId, "personId")!, type: text(input.type, "type") as "national_id" | "passport" | "driver_license" | "other", countryCode: text(input.countryCode, "countryCode")!, ...protectedValue }), 201)
  }
  if (path === "/v1/people/relationships") {
    await authenticate(ctx, request, "people:write", organizationId)
    return response({ relationshipId: await ctx.runMutation(internal.v1People.relate, { organizationPublicId: organizationId, fromPersonPublicId: text(input.fromPersonId, "fromPersonId")!, toPersonPublicId: text(input.toPersonId, "toPersonId")!, type: text(input.type, "type") as "legal_guardian" | "parent" | "spouse" | "dependent" | "emergency_contact" | "other", canBook: boolean(input.canBook, "canBook", false) }) }, 201)
  }
  if (path === "/v1/insurance/payers") {
    const auth = await authenticate(ctx, request, "insurance:directory", organizationId)
    return response(await ctx.runMutation(internal.v1Insurance.createPayer, { principalId: auth.principalId, countryCode: text(input.countryCode, "countryCode")!, name: text(input.name, "name")!, shortName: text(input.shortName, "shortName")! }), 201)
  }
  if (path === "/v1/insurance/coverages") {
    await authenticate(ctx, request, "pii:write", organizationId)
    const protectedValue = await protectSensitive(text(input.memberNumber, "memberNumber")!)
    return response(await ctx.runMutation(internal.v1Insurance.createCoverage, { organizationPublicId: organizationId, personPublicId: text(input.personId, "personId")!, payerPublicId: text(input.payerId, "payerId")!, policyHolderPersonPublicId: text(input.policyHolderPersonId, "policyHolderPersonId", true), memberNumberEncrypted: protectedValue.encryptedValue, memberNumberBlindHash: protectedValue.blindHash, memberNumberMasked: protectedValue.maskedValue, encryptionKeyVersion: protectedValue.encryptionKeyVersion, validFrom: text(input.validFrom, "validFrom", true), validThrough: text(input.validThrough, "validThrough", true) }), 201)
  }
  if (path === "/v1/providers/credentials") {
    await authenticate(ctx, request, "pii:write", organizationId)
    const protectedValue = await protectSensitive(text(input.value, "value")!)
    return response(await ctx.runMutation(internal.v1Insurance.createProviderCredential, { organizationPublicId: organizationId, personPublicId: text(input.personId, "personId")!, type: text(input.type, "type") as "exequatur" | "professional_license" | "board_certification" | "other", countryCode: text(input.countryCode, "countryCode")!, issuer: text(input.issuer, "issuer")!, valueEncrypted: protectedValue.encryptedValue, valueMasked: protectedValue.maskedValue, blindHash: protectedValue.blindHash, encryptionKeyVersion: protectedValue.encryptionKeyVersion, validThrough: text(input.validThrough, "validThrough", true) }), 201)
  }
  if (path === "/v1/calendars") {
    await authenticate(ctx, request, "operations:write", organizationId)
    return response(await ctx.runMutation(internal.v1Catalog.createCalendar, { organizationPublicId: organizationId, name: text(input.name, "name")!, timezone: text(input.timezone, "timezone")!, ownerType: text(input.ownerType, "ownerType") as "organization" | "location" | "service" | "resource", locationPublicId: text(input.locationId, "locationId", true), servicePublicId: text(input.serviceId, "serviceId", true), resourcePublicId: text(input.resourceId, "resourceId", true) }), 201)
  }
  if (path === "/v1/calendars/rules") {
    await authenticate(ctx, request, "operations:write", organizationId)
    if (!Array.isArray(input.rules)) throw new ConvexError({ code: "INVALID_INPUT", message: "rules must be an array", details: {} })
    const rules = input.rules.map((raw) => { const rule = raw as JsonObject; return { weekday: number(rule.weekday, "weekday"), startMinute: number(rule.startMinute, "startMinute"), endMinute: number(rule.endMinute, "endMinute"), shift: text(rule.shift, "shift") as "morning" | "afternoon" | "evening" } })
    return response(await ctx.runMutation(internal.v1Catalog.setWeeklyRules, { organizationPublicId: organizationId, calendarPublicId: text(input.calendarId, "calendarId")!, rules }))
  }
  if (path === "/v1/calendars/exceptions") {
    await authenticate(ctx, request, "operations:write", organizationId)
    if (!Array.isArray(input.windows)) throw new ConvexError({ code: "INVALID_INPUT", message: "windows must be an array", details: {} })
    const windows = input.windows.map((raw) => { const window = raw as JsonObject; return { startMinute: number(window.startMinute, "startMinute"), endMinute: number(window.endMinute, "endMinute"), shift: text(window.shift, "shift") as "morning" | "afternoon" | "evening" } })
    return response({ exceptionId: await ctx.runMutation(internal.v1Catalog.addException, { organizationPublicId: organizationId, calendarPublicId: text(input.calendarId, "calendarId")!, localDate: text(input.localDate, "localDate")!, type: text(input.type, "type") as "closed" | "open" | "custom_hours", windows, reason: text(input.reason, "reason")! }) })
  }
  if (path === "/v1/classes/series") {
    await authenticate(ctx, request, "operations:write", organizationId)
    return response(await ctx.runMutation(internal.v1Catalog.createSeries, { organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, name: text(input.name, "name")!, timezone: text(input.timezone, "timezone")!, recurrenceRule: text(input.recurrenceRule, "recurrenceRule")!, startsOn: text(input.startsOn, "startsOn")!, endsOn: text(input.endsOn, "endsOn", true), enrollmentMode: text(input.enrollmentMode, "enrollmentMode") as "occurrence" | "series" | "both" }), 201)
  }
  if (path === "/v1/classes/sessions") {
    await authenticate(ctx, request, "operations:write", organizationId)
    return response(await ctx.runMutation(internal.v1Catalog.createSession, { organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, locationPublicId: text(input.locationId, "locationId", true), seriesPublicId: text(input.seriesId, "seriesId", true), startsAt: Date.parse(text(input.startsAt, "startsAt")!), endsAt: Date.parse(text(input.endsAt, "endsAt")!), localDate: text(input.localDate, "localDate")!, timezone: text(input.timezone, "timezone")!, capacity: number(input.capacity, "capacity"), resourcePublicIds: strings(input.resourceIds, "resourceIds") }), 201)
  }
  if (path === "/v1/availability/summarize") {
    await authenticate(ctx, request, "availability:read", organizationId)
    return response({ data: await ctx.runMutation(internal.v1Availability.summarize, { organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, locationPublicId: text(input.locationId, "locationId", true), fromLocalDate: text(input.fromLocalDate, "fromLocalDate")!, days: number(input.days, "days", 7), modality: text(input.modality, "modality", true) as "onsite" | "virtual" | "at_customer_location" | "hybrid" | undefined }) })
  }
  if (path === "/v1/availability/options") {
    await authenticate(ctx, request, "availability:read", organizationId)
    return response({ data: await ctx.runMutation(internal.v1Availability.listOptions, { organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, locationPublicId: text(input.locationId, "locationId", true), fromLocalDate: text(input.fromLocalDate, "fromLocalDate")!, days: number(input.days, "days", 7), shifts: strings(input.shifts, "shifts") as Array<"morning" | "afternoon" | "evening">, modality: text(input.modality, "modality", true) as "onsite" | "virtual" | "at_customer_location" | "hybrid" | undefined, capacityUnits: number(input.capacityUnits, "capacityUnits", 1), limit: number(input.limit, "limit", 5) }) })
  }
  if (path === "/v1/bookings") {
    const auth = await authenticate(ctx, request, "bookings:write", organizationId)
    const idempotencyKey = request.headers.get("idempotency-key")
    if (!idempotencyKey) throw new ConvexError({ code: "INVALID_INPUT", message: "Idempotency-Key header is required", details: {} })
    return response(await ctx.runMutation(internal.v1Bookings.create, { principalId: auth.principalId, organizationPublicId: organizationId, offerId: text(input.offerId, "offerId")!, idempotencyKey, requestHash: await sha256(JSON.stringify(input)), bookerPersonPublicId: text(input.bookerPersonId, "bookerPersonId")!, participantPersonPublicIds: strings(input.participantPersonIds, "participantPersonIds"), patientWarnedAboutAutoRelease: boolean(input.patientWarnedAboutAutoRelease, "patientWarnedAboutAutoRelease", false), source: "agent" }), 201)
  }
  if (path === "/v1/bookings/transition") {
    const auth = await authenticate(ctx, request, "bookings:write", organizationId)
    return response(await ctx.runMutation(internal.v1Bookings.transition, { principalId: auth.principalId, organizationPublicId: organizationId, bookingPublicId: text(input.bookingId, "bookingId")!, action: text(input.action, "action") as "confirm" | "cancel_by_patient" | "cancel_by_business" | "complete" | "mark_no_show", reason: text(input.reason, "reason", true) }))
  }
  if (path === "/v1/bookings/reschedule") {
    const auth = await authenticate(ctx, request, "bookings:write", organizationId)
    const idempotencyKey = request.headers.get("idempotency-key")
    if (!idempotencyKey) throw new ConvexError({ code: "INVALID_INPUT", message: "Idempotency-Key header is required", details: {} })
    return response(await ctx.runMutation(internal.v1Bookings.reschedule, { principalId: auth.principalId, organizationPublicId: organizationId, bookingPublicId: text(input.bookingId, "bookingId")!, offerId: text(input.offerId, "offerId")!, idempotencyKey, requestHash: await sha256(JSON.stringify(input)), reason: text(input.reason, "reason")! }))
  }
  if (path === "/v1/queue/check-in") {
    const auth = await authenticate(ctx, request, "queue:write", organizationId)
    const rawQrToken = text(input.qrToken, "qrToken", true) ?? `qr_${crypto.randomUUID().replaceAll("-", "")}`
    const result = await ctx.runMutation(internal.v1Queue.checkIn, { principalId: auth.principalId, organizationPublicId: organizationId, bookingPublicId: text(input.bookingId, "bookingId", true), servicePublicId: text(input.serviceId, "serviceId")!, locationPublicId: text(input.locationId, "locationId")!, personPublicId: text(input.personId, "personId")!, localDate: text(input.localDate, "localDate")!, shift: text(input.shift, "shift") as "morning" | "afternoon" | "evening", qrTokenHash: await sha256(rawQrToken) })
    return response({ ...result, qrToken: input.qrToken ? undefined : rawQrToken, disclaimer: "El orden estimado puede cambiar. El ticket se asigna de forma autoritativa al completar el check-in." }, 201)
  }
  if (path === "/v1/waitlist") {
    const auth = await authenticate(ctx, request, "waitlist:write", organizationId)
    return response(await ctx.runMutation(internal.v1Waitlist.join, { principalId: auth.principalId, organizationPublicId: organizationId, servicePublicId: text(input.serviceId, "serviceId")!, locationPublicId: text(input.locationId, "locationId", true), personPublicId: text(input.personId, "personId")!, preferredDates: strings(input.preferredDates, "preferredDates"), preferredShifts: strings(input.preferredShifts, "preferredShifts") as Array<"morning" | "afternoon" | "evening">, modality: text(input.modality, "modality", true) as "onsite" | "virtual" | "at_customer_location" | "hybrid" | undefined, warnedAutoRelease: boolean(input.warnedAutoRelease, "warnedAutoRelease", false) }), 201)
  }
  if (path === "/v1/waitlist/offer") {
    const auth = await authenticate(ctx, request, "waitlist:manage", organizationId)
    return response(await ctx.runMutation(internal.v1Waitlist.offerReleasedSpace, { principalId: auth.principalId, organizationPublicId: organizationId, availabilityOfferPublicId: text(input.availabilityOfferId, "availabilityOfferId")! }))
  }
  if (path === "/v1/waitlist/accept") {
    const auth = await authenticate(ctx, request, "waitlist:write", organizationId)
    return response(await ctx.runMutation(internal.v1Waitlist.accept, { principalId: auth.principalId, organizationPublicId: organizationId, waitlistOfferPublicId: text(input.waitlistOfferId, "waitlistOfferId")! }))
  }
  if (path === "/v1/organizations/publish") {
    const auth = await authenticate(ctx, request, "organization:publish", organizationId)
    return response(await ctx.runMutation(internal.v1Organizations.publish, { organizationPublicId: organizationId, principalId: auth.principalId, explicitConsent: boolean(input.explicitConsent, "explicitConsent") }))
  }
  if (path === "/v1/onboarding/provision-pilot") {
    await authenticate(ctx, request, "onboarding:provision", organizationId)
    return response(await ctx.runAction(internal.v1Provisioning.runPilot, { organizationPublicId: organizationId, whatsappNumber: text(input.whatsappNumber, "whatsappNumber")! }))
  }
  if (path === "/v1/holidays/import") {
    const auth = await authenticate(ctx, request, "holidays:import", organizationId)
    if (!Array.isArray(input.occurrences)) throw new ConvexError({ code: "INVALID_INPUT", message: "occurrences must be an array", details: {} })
    const occurrences = input.occurrences.map((raw) => { const item = raw as JsonObject; return { localDate: text(item.localDate, "localDate")!, observedDate: text(item.observedDate, "observedDate", true), name: text(item.name, "name")! } })
    return response(await ctx.runMutation(internal.v1Holidays.importOfficial, { principalId: auth.principalId, countryCode: text(input.countryCode, "countryCode")!, subdivisionCode: text(input.subdivisionCode, "subdivisionCode", true), sourceUrl: text(input.sourceUrl, "sourceUrl")!, fetchedAt: Date.now(), occurrences }))
  }
  if (path === "/v1/holidays/opening-decision") {
    const auth = await authenticate(ctx, request, "operations:write", organizationId)
    if (!Array.isArray(input.windows)) throw new ConvexError({ code: "INVALID_INPUT", message: "windows must be an array", details: {} })
    const windows = input.windows.map((raw) => { const window = raw as JsonObject; return { startMinute: number(window.startMinute, "startMinute"), endMinute: number(window.endMinute, "endMinute") } })
    return response(await ctx.runMutation(internal.v1Holidays.decideOpening, { principalId: auth.principalId, organizationPublicId: organizationId, locationPublicId: text(input.locationId, "locationId")!, holidayPublicId: text(input.holidayId, "holidayId")!, decision: text(input.decision, "decision") as "open" | "closed" | "custom_hours", windows }))
  }
  return response({ error: { code: "NOT_FOUND", message: "Route not found" } }, 404)
}

async function get(ctx: ActionCtx, request: Request, path: string): Promise<Response> {
  if (path === "/v1/openapi.json") return response(openApiDocument)
  if (path === "/v1/agent/runtime-bundle") {
    const organizationId = new URL(request.url).searchParams.get("organizationId") ?? ""
    await authenticate(ctx, request, "agent:runtime", organizationId)
    return response(await ctx.runQuery(internal.v1Runtime.bundle, { organizationPublicId: organizationId }))
  }
  return response({ error: { code: "NOT_FOUND", message: "Route not found" } }, 404)
}

const api = httpAction(async (ctx, request) => {
  try {
    const path = new URL(request.url).pathname.replace(/\/$/, "")
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers })
    if (request.method === "GET") return await get(ctx, request, path)
    if (request.method === "POST") return await post(ctx, request, path)
    return response({ error: { code: "METHOD_NOT_ALLOWED", message: "Method not allowed" } }, 405)
  } catch (error) {
    const data = error instanceof ConvexError ? error.data as { code?: string, message?: string, details?: JsonObject } : null
    const code = data?.code ?? "INTERNAL_ERROR"
    const status = code === "AUTHENTICATION_REQUIRED" ? 401 : code === "INSUFFICIENT_SCOPE" || code === "TENANT_SCOPE_VIOLATION" ? 403 : code === "NOT_FOUND" ? 404 : code.includes("UNAVAILABLE") || code.includes("CAPACITY") || code.includes("OFFER") || code.includes("IDEMPOTENCY") ? 409 : 400
    return response({ error: { code, message: data?.message ?? "Request failed", details: data?.details ?? {} } }, status)
  }
})

const router = httpRouter()
router.route({ pathPrefix: "/v1/", method: "GET", handler: api })
router.route({ pathPrefix: "/v1/", method: "POST", handler: api })
router.route({ pathPrefix: "/v1/", method: "OPTIONS", handler: api })

export default router
