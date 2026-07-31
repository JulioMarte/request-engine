import { v } from "convex/values"
import { internalMutation, internalQuery, query } from "./_generated/server"
import { bookingMode, modality, price, requiredField, shift } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"

export const createService = internalMutation({
  args: {
    organizationPublicId: v.string(), name: v.string(), description: v.string(), synonyms: v.array(v.string()), bookingMode,
    modalities: v.array(modality), durationMinutes: v.number(), slotIntervalMinutes: v.number(), bufferBeforeMinutes: v.number(), bufferAfterMinutes: v.number(), capacity: v.number(), price,
    requiredFields: v.array(requiredField), seriesEnrollment: v.union(v.literal("occurrence"), v.literal("series"), v.literal("both")), autoReleaseUnconfirmed: v.boolean(), neverAutoCancel: v.boolean(), waitlistEnabled: v.boolean(),
  },
  returns: v.object({ serviceId: v.string(), status: v.literal("active") }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    if (args.durationMinutes <= 0 || args.slotIntervalMinutes <= 0 || args.capacity < 1) fail("INVALID_INPUT", "Duration, interval and capacity must be positive")
    if (!args.modalities.length) fail("MISSING_REQUIRED_FIELDS", "At least one modality is required")
    const now = Date.now()
    const { organizationPublicId: _organizationPublicId, ...service } = args
    void _organizationPublicId
    const id = await ctx.db.insert("services", { ...service, organizationId: organization._id, virtualProvider: "manual_link", status: "active", publicId: "pending", createdAt: now, updatedAt: now })
    const serviceId = publicId("svc", id)
    await ctx.db.patch(id, { publicId: serviceId })
    return { serviceId, status: "active" as const }
  },
})

export const createLocation = internalMutation({
  args: { organizationPublicId: v.string(), name: v.string(), terminology: v.string(), timezone: v.string(), countryCode: v.string(), subdivisionCode: v.optional(v.string()), address: v.optional(v.object({ line1: v.string(), line2: v.optional(v.string()), city: v.string(), postalCode: v.optional(v.string()) })) },
  returns: v.object({ locationId: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const now = Date.now()
    const id = await ctx.db.insert("locations", { publicId: "pending", organizationId: organization._id, name: args.name, terminology: args.terminology, timezone: args.timezone, countryCode: args.countryCode, subdivisionCode: args.subdivisionCode, address: args.address, status: "active", createdAt: now, updatedAt: now })
    const locationId = publicId("loc", id)
    await ctx.db.patch(id, { publicId: locationId })
    return { locationId }
  },
})

export const createResource = internalMutation({
  args: { organizationPublicId: v.string(), locationPublicId: v.optional(v.string()), name: v.string(), type: v.union(v.literal("staff"), v.literal("room"), v.literal("equipment"), v.literal("vehicle"), v.literal("other")), capacity: v.number() },
  returns: v.object({ resourceId: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    if (location && location.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Location is outside the organization")
    const now = Date.now()
    const id = await ctx.db.insert("resources", { publicId: "pending", organizationId: organization._id, locationId: location?._id, name: args.name, type: args.type, capacity: args.capacity, status: "active", createdAt: now, updatedAt: now })
    const resourceId = publicId("res", id)
    await ctx.db.patch(id, { publicId: resourceId })
    return { resourceId }
  },
})

export const requireResource = internalMutation({
  args: { organizationPublicId: v.string(), servicePublicId: v.string(), resourceType: v.union(v.literal("staff"), v.literal("room"), v.literal("equipment"), v.literal("vehicle"), v.literal("other")), quantity: v.number(), allowedResourcePublicIds: v.array(v.string()), required: v.boolean() },
  returns: v.null(),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    if (!organization || !service) fail("NOT_FOUND", "Organization or service not found")
    if (service.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Service is outside the organization")
    const resources = await Promise.all(args.allowedResourcePublicIds.map((id) => ctx.db.query("resources").withIndex("by_public_id", (q) => q.eq("publicId", id)).unique()))
    if (resources.some((item) => !item || item.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "A resource is outside the organization")
    await ctx.db.insert("serviceResourceRequirements", { organizationId: organization._id, serviceId: service._id, resourceType: args.resourceType, quantity: args.quantity, allowedResourceIds: resources.map((item) => item!._id), required: args.required })
    return null
  },
})

export const createCalendar = internalMutation({
  args: { organizationPublicId: v.string(), name: v.string(), timezone: v.string(), ownerType: v.union(v.literal("organization"), v.literal("location"), v.literal("service"), v.literal("resource")), locationPublicId: v.optional(v.string()), servicePublicId: v.optional(v.string()), resourcePublicId: v.optional(v.string()) },
  returns: v.object({ calendarId: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    const service = args.servicePublicId ? await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId!)).unique() : null
    const resource = args.resourcePublicId ? await ctx.db.query("resources").withIndex("by_public_id", (q) => q.eq("publicId", args.resourcePublicId!)).unique() : null
    for (const item of [location, service, resource]) if (item && item.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Calendar owner is outside the organization")
    const now = Date.now()
    const id = await ctx.db.insert("calendars", { publicId: "pending", organizationId: organization._id, name: args.name, timezone: args.timezone, ownerType: args.ownerType, locationId: location?._id, serviceId: service?._id, resourceId: resource?._id, createdAt: now, updatedAt: now })
    const calendarId = publicId("cal", id)
    await ctx.db.patch(id, { publicId: calendarId })
    return { calendarId }
  },
})

export const setWeeklyRules = internalMutation({
  args: { organizationPublicId: v.string(), calendarPublicId: v.string(), rules: v.array(v.object({ weekday: v.number(), startMinute: v.number(), endMinute: v.number(), shift })) },
  returns: v.object({ count: v.number() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const calendar = await ctx.db.query("calendars").filter((q) => q.eq(q.field("publicId"), args.calendarPublicId)).unique()
    if (!organization || !calendar) fail("NOT_FOUND", "Organization or calendar not found")
    if (calendar.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Calendar is outside the organization")
    const existing = await ctx.db.query("weeklyScheduleRules").filter((q) => q.eq(q.field("calendarId"), calendar._id)).collect()
    await Promise.all(existing.map((item) => ctx.db.delete(item._id)))
    const now = Date.now()
    for (const rule of args.rules) {
      if (rule.weekday < 0 || rule.weekday > 6 || rule.startMinute < 0 || rule.endMinute > 1440 || rule.startMinute >= rule.endMinute) fail("INVALID_INPUT", "Invalid weekly schedule rule")
      await ctx.db.insert("weeklyScheduleRules", { organizationId: organization._id, calendarId: calendar._id, ...rule, createdAt: now, updatedAt: now })
    }
    return { count: args.rules.length }
  },
})

export const addException = internalMutation({
  args: { organizationPublicId: v.string(), calendarPublicId: v.string(), localDate: v.string(), type: v.union(v.literal("closed"), v.literal("open"), v.literal("custom_hours")), windows: v.array(v.object({ startMinute: v.number(), endMinute: v.number(), shift })), reason: v.string() },
  returns: v.string(),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const calendar = await ctx.db.query("calendars").filter((q) => q.eq(q.field("publicId"), args.calendarPublicId)).unique()
    if (!organization || !calendar) fail("NOT_FOUND", "Organization or calendar not found")
    if (calendar.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Calendar is outside the organization")
    const now = Date.now()
    const existing = await ctx.db.query("scheduleExceptions").withIndex("by_calendar_date", (q) => q.eq("calendarId", calendar._id).eq("localDate", args.localDate)).unique()
    if (existing) {
      await ctx.db.patch(existing._id, { type: args.type, windows: args.windows, reason: args.reason, updatedAt: now })
      return existing._id
    }
    return ctx.db.insert("scheduleExceptions", { organizationId: organization._id, calendarId: calendar._id, localDate: args.localDate, type: args.type, windows: args.windows, reason: args.reason, createdAt: now, updatedAt: now })
  },
})

export const createSeries = internalMutation({
  args: { organizationPublicId: v.string(), servicePublicId: v.string(), name: v.string(), timezone: v.string(), recurrenceRule: v.string(), startsOn: v.string(), endsOn: v.optional(v.string()), enrollmentMode: v.union(v.literal("occurrence"), v.literal("series"), v.literal("both")) },
  returns: v.object({ seriesId: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    if (!organization || !service) fail("NOT_FOUND", "Organization or service not found")
    if (service.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Service is outside the organization")
    if (service.bookingMode !== "class_session") fail("INVALID_INPUT", "Series require a class_session service")
    const now = Date.now()
    const id = await ctx.db.insert("sessionSeries", { publicId: "pending", organizationId: organization._id, serviceId: service._id, name: args.name, timezone: args.timezone, recurrenceRule: args.recurrenceRule, startsOn: args.startsOn, endsOn: args.endsOn, enrollmentMode: args.enrollmentMode, status: "active", createdAt: now, updatedAt: now })
    const seriesId = publicId("ser", id)
    await ctx.db.patch(id, { publicId: seriesId })
    return { seriesId }
  },
})

export const createSession = internalMutation({
  args: { organizationPublicId: v.string(), servicePublicId: v.string(), locationPublicId: v.optional(v.string()), seriesPublicId: v.optional(v.string()), startsAt: v.number(), endsAt: v.number(), localDate: v.string(), timezone: v.string(), capacity: v.number(), resourcePublicIds: v.array(v.string()) },
  returns: v.object({ sessionId: v.string() }),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    const series = args.seriesPublicId ? await ctx.db.query("sessionSeries").filter((q) => q.eq(q.field("publicId"), args.seriesPublicId)).unique() : null
    const resources = await Promise.all(args.resourcePublicIds.map((id) => ctx.db.query("resources").withIndex("by_public_id", (q) => q.eq("publicId", id)).unique()))
    if (!organization || !service) fail("NOT_FOUND", "Organization or service not found")
    if (service.organizationId !== organization._id || (location && location.organizationId !== organization._id) || (series && series.organizationId !== organization._id) || resources.some((item) => !item || item.organizationId !== organization._id)) fail("TENANT_SCOPE_VIOLATION", "Session context crosses organizations")
    if (service.bookingMode !== "class_session" || args.startsAt >= args.endsAt || args.capacity < 1) fail("INVALID_INPUT", "Invalid class session")
    const now = Date.now()
    const id = await ctx.db.insert("serviceSessions", { publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: location?._id, seriesId: series?._id, startsAt: args.startsAt, endsAt: args.endsAt, localDate: args.localDate, timezone: args.timezone, capacity: args.capacity, reservedCount: 0, resourceIds: resources.map((item) => item!._id), status: "scheduled", createdAt: now, updatedAt: now })
    const sessionId = publicId("ses", id)
    await ctx.db.patch(id, { publicId: sessionId })
    return { sessionId }
  },
})

export const search = internalQuery({
  args: { organizationPublicId: v.string(), query: v.string(), bookingMode: v.optional(bookingMode), modality: v.optional(modality), limit: v.number() },
  returns: v.array(v.object({ serviceId: v.string(), name: v.string(), description: v.string(), bookingMode, modalities: v.array(modality), durationMinutes: v.number(), capacity: v.number(), price })),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) fail("NOT_FOUND", "Organization not found")
    const normalized = args.query.trim().toLocaleLowerCase()
    const items = await ctx.db.query("services").withIndex("by_organization_status", (q) => q.eq("organizationId", organization._id).eq("status", "active")).take(100)
    return items.filter((item) => (!args.bookingMode || item.bookingMode === args.bookingMode) && (!args.modality || item.modalities.includes(args.modality)) && (!normalized || [item.name, item.description, ...item.synonyms].some((value) => value.toLocaleLowerCase().includes(normalized)))).slice(0, Math.min(args.limit, 5)).map((item) => ({ serviceId: item.publicId, name: item.name, description: item.description, bookingMode: item.bookingMode, modalities: item.modalities, durationMinutes: item.durationMinutes, capacity: item.capacity, price: item.price }))
  },
})

export const listServices = query({
  args: { organizationPublicId: v.string() },
  returns: v.array(v.object({ serviceId: v.string(), name: v.string(), bookingMode, durationMinutes: v.number(), capacity: v.number(), status: v.string(), price })),
  handler: async (ctx, args) => {
    if (!(await ctx.auth.getUserIdentity())) return []
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) return []
    const services = await ctx.db.query("services").withIndex("by_organization_status", (q) => q.eq("organizationId", organization._id)).collect()
    return services.map((item) => ({ serviceId: item.publicId, name: item.name, bookingMode: item.bookingMode, durationMinutes: item.durationMinutes, capacity: item.capacity, status: item.status, price: item.price }))
  },
})
