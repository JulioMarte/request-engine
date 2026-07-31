import { v } from "convex/values"
import type { Doc, Id } from "./_generated/dataModel"
import type { MutationCtx } from "./_generated/server"
import { internalMutation } from "./_generated/server"
import { bookingMode, modality, price, shift } from "./domainValidators"
import { fail } from "./lib/errors"
import { publicId } from "./lib/ids"
import { addLocalDays, localLabel, shiftForMinute, weekday, zonedDateTimeToUtc, type ShiftName } from "./lib/time"

const option = v.object({
  offerId: v.string(), serviceId: v.string(), serviceName: v.string(), bookingMode, modality,
  startsAt: v.string(), endsAt: v.string(), localDate: v.string(), localLabel: v.string(), timezone: v.string(),
  shift: v.optional(shift), capacityUnits: v.number(), price, expiresAt: v.string(),
})

const activeBookingStatuses = new Set(["pending_confirmation", "confirmed", "checked_in", "in_service"])

async function resourceIsAvailable(ctx: MutationCtx, resourceId: Id<"resources">, localDate: string, startsAt: number, endsAt: number) {
  const allocations = await ctx.db.query("bookingAllocations").withIndex("by_resource_date_start", (q) => q.eq("resourceId", resourceId).eq("localDate", localDate)).collect()
  return !allocations.some((allocation) => allocation.status === "held" && allocation.startsAt < endsAt && allocation.endsAt > startsAt)
}

async function selectResources(ctx: MutationCtx, service: Doc<"services">, localDate: string, startsAt: number, endsAt: number) {
  const requirements = await ctx.db.query("serviceResourceRequirements").withIndex("by_service", (q) => q.eq("serviceId", service._id)).collect()
  const selected: Id<"resources">[] = []
  for (const requirement of requirements) {
    let candidates = requirement.allowedResourceIds
    if (!candidates.length) {
      const resources = await ctx.db.query("resources").withIndex("by_organization", (q) => q.eq("organizationId", service.organizationId)).collect()
      candidates = resources.filter((item) => item.type === requirement.resourceType && item.status === "active").map((item) => item._id)
    }
    const available: Id<"resources">[] = []
    for (const candidate of candidates) {
      if (!selected.includes(candidate) && await resourceIsAvailable(ctx, candidate, localDate, startsAt, endsAt)) available.push(candidate)
      if (available.length >= requirement.quantity) break
    }
    if (requirement.required && available.length < requirement.quantity) return null
    selected.push(...available)
  }
  return selected
}

async function remainingServiceCapacity(ctx: MutationCtx, service: Doc<"services">, startsAt: number, endsAt: number) {
  const bookings = await ctx.db.query("bookings").withIndex("by_organization_start", (q) => q.eq("organizationId", service.organizationId).lt("startsAt", endsAt)).collect()
  const used = bookings.filter((booking) => booking.serviceId === service._id && activeBookingStatuses.has(booking.status) && booking.endsAt > startsAt).reduce((sum, booking) => sum + booking.capacityUnits, 0)
  return service.capacity - used
}

async function calendarFor(ctx: MutationCtx, service: Doc<"services">, locationId?: Id<"locations">) {
  const serviceCalendar = await ctx.db.query("calendars").withIndex("by_service", (q) => q.eq("serviceId", service._id)).first()
  if (serviceCalendar) return serviceCalendar
  const calendars = await ctx.db.query("calendars").withIndex("by_organization", (q) => q.eq("organizationId", service.organizationId)).collect()
  return calendars.find((item) => locationId && item.locationId === locationId) ?? calendars.find((item) => item.ownerType === "organization") ?? null
}

async function windowsFor(ctx: MutationCtx, calendar: Doc<"calendars">, localDate: string) {
  const exception = await ctx.db.query("scheduleExceptions").withIndex("by_calendar_date", (q) => q.eq("calendarId", calendar._id).eq("localDate", localDate)).unique()
  if (exception?.type === "closed") return []
  if (exception && (exception.type === "open" || exception.type === "custom_hours")) return exception.windows
  const rules = await ctx.db.query("weeklyScheduleRules").withIndex("by_calendar_weekday", (q) => q.eq("calendarId", calendar._id).eq("weekday", weekday(localDate))).collect()
  return rules.filter((rule) => (!rule.effectiveFrom || rule.effectiveFrom <= localDate) && (!rule.effectiveThrough || rule.effectiveThrough >= localDate))
}

export const listOptions = internalMutation({
  args: {
    organizationPublicId: v.string(), servicePublicId: v.string(), locationPublicId: v.optional(v.string()), fromLocalDate: v.string(), days: v.number(),
    shifts: v.array(shift), modality: v.optional(modality), capacityUnits: v.number(), limit: v.number(),
  },
  returns: v.array(option),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    if (!organization || !service) fail("NOT_FOUND", "Organization or service not found")
    if (service.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Service is outside the organization")
    if (service.status !== "active") fail("INVALID_STATE_TRANSITION", "Service is not active")
    const selectedModality = args.modality ?? service.modalities[0]
    if (!service.modalities.includes(selectedModality)) fail("INVALID_INPUT", "The service does not support this modality")
    if (args.capacityUnits < 1 || args.capacityUnits > service.capacity) fail("CAPACITY_EXCEEDED", "Requested participants exceed service capacity")
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    if (location && location.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Location is outside the organization")
    const calendar = await calendarFor(ctx, service, location?._id)
    if (!calendar) fail("MISSING_REQUIRED_FIELDS", "No operating calendar is configured for this service")
    const maximum = Math.min(Math.max(args.limit, 1), 5)
    const candidates: Array<{ startsAt: number, endsAt: number, localDate: string, shift?: ShiftName, resourceIds: Id<"resources">[], sessionId?: Id<"serviceSessions"> }> = []

    if (service.bookingMode === "class_session") {
      const from = zonedDateTimeToUtc(args.fromLocalDate, 0, calendar.timezone)
      const through = zonedDateTimeToUtc(addLocalDays(args.fromLocalDate, Math.min(args.days, 31)), 0, calendar.timezone)
      const sessions = await ctx.db.query("serviceSessions").withIndex("by_service_start", (q) => q.eq("serviceId", service._id).gte("startsAt", from).lt("startsAt", through)).collect()
      for (const session of sessions) {
        const sessionShift = shiftForMinute(Number(new Intl.DateTimeFormat("en-US", { timeZone: session.timezone, hour: "numeric", minute: "numeric", hourCycle: "h23" }).formatToParts(new Date(session.startsAt)).find((part) => part.type === "hour")?.value ?? 0) * 60)
        if (session.status === "scheduled" && session.capacity - session.reservedCount >= args.capacityUnits && (!args.shifts.length || args.shifts.includes(sessionShift))) candidates.push({ startsAt: session.startsAt, endsAt: session.endsAt, localDate: session.localDate, shift: sessionShift, resourceIds: session.resourceIds, sessionId: session._id })
        if (candidates.length >= maximum) break
      }
    } else {
      for (let dayOffset = 0; dayOffset < Math.min(Math.max(args.days, 1), 31) && candidates.length < maximum; dayOffset += 1) {
        const localDate = addLocalDays(args.fromLocalDate, dayOffset)
        const windows = await windowsFor(ctx, calendar, localDate)
        for (const window of windows) {
          if (args.shifts.length && !args.shifts.includes(window.shift)) continue
          const increments = service.bookingMode === "arrival_window" ? [window.startMinute] : Array.from({ length: Math.max(0, Math.floor((window.endMinute - window.startMinute - service.durationMinutes) / service.slotIntervalMinutes) + 1) }, (_, index) => window.startMinute + index * service.slotIntervalMinutes)
          for (const minute of increments) {
            const startsAt = zonedDateTimeToUtc(localDate, minute, calendar.timezone)
            const endsAt = service.bookingMode === "arrival_window" ? zonedDateTimeToUtc(localDate, window.endMinute, calendar.timezone) : startsAt + service.durationMinutes * 60_000
            if (startsAt <= Date.now()) continue
            const remaining = await remainingServiceCapacity(ctx, service, startsAt, endsAt)
            if (remaining < args.capacityUnits) continue
            const resourceIds = await selectResources(ctx, service, localDate, startsAt - service.bufferBeforeMinutes * 60_000, endsAt + service.bufferAfterMinutes * 60_000)
            if (resourceIds === null) continue
            candidates.push({ startsAt, endsAt, localDate, shift: window.shift, resourceIds })
            if (candidates.length >= maximum) break
          }
          if (candidates.length >= maximum) break
        }
      }
    }

    const result = []
    for (const candidate of candidates) {
      const now = Date.now()
      const expiresAt = now + 5 * 60_000
      const id = await ctx.db.insert("availabilityOffers", {
        publicId: "pending", organizationId: organization._id, serviceId: service._id, locationId: location?._id, sessionId: candidate.sessionId,
        bookingMode: service.bookingMode, startsAt: candidate.startsAt, endsAt: candidate.endsAt, localDate: candidate.localDate, timezone: calendar.timezone,
        shift: candidate.shift, resourceIds: candidate.resourceIds, capacityUnits: args.capacityUnits,
        snapshot: { serviceName: service.name, durationMinutes: service.durationMinutes, modality: selectedModality, price: service.price },
        expiresAt, createdAt: now,
      })
      const offerId = publicId("off", id)
      await ctx.db.patch(id, { publicId: offerId })
      result.push({ offerId, serviceId: service.publicId, serviceName: service.name, bookingMode: service.bookingMode, modality: selectedModality, startsAt: new Date(candidate.startsAt).toISOString(), endsAt: new Date(candidate.endsAt).toISOString(), localDate: candidate.localDate, localLabel: localLabel(candidate.startsAt, calendar.timezone, organization.locale), timezone: calendar.timezone, shift: candidate.shift, capacityUnits: args.capacityUnits, price: service.price, expiresAt: new Date(expiresAt).toISOString() })
    }
    return result
  },
})

export const summarize = internalMutation({
  args: { organizationPublicId: v.string(), servicePublicId: v.string(), locationPublicId: v.optional(v.string()), fromLocalDate: v.string(), days: v.number(), modality: v.optional(modality) },
  returns: v.array(v.object({ localDate: v.string(), shifts: v.array(v.object({ shift, available: v.boolean() })) })),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    const service = await ctx.db.query("services").withIndex("by_public_id", (q) => q.eq("publicId", args.servicePublicId)).unique()
    if (!organization || !service) fail("NOT_FOUND", "Organization or service not found")
    if (service.organizationId !== organization._id) fail("TENANT_SCOPE_VIOLATION", "Service is outside the organization")
    const location = args.locationPublicId ? await ctx.db.query("locations").withIndex("by_public_id", (q) => q.eq("publicId", args.locationPublicId!)).unique() : null
    const calendar = await calendarFor(ctx, service, location?._id)
    if (!calendar) fail("MISSING_REQUIRED_FIELDS", "No operating calendar is configured")
    const result = []
    for (let dayOffset = 0; dayOffset < Math.min(Math.max(args.days, 1), 14); dayOffset += 1) {
      const localDate = addLocalDays(args.fromLocalDate, dayOffset)
      const windows = await windowsFor(ctx, calendar, localDate)
      result.push({ localDate, shifts: (["morning", "afternoon", "evening"] as const).map((name) => ({ shift: name, available: windows.some((window) => window.shift === name) })) })
    }
    return result
  },
})
