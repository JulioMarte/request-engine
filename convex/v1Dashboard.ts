import { v } from "convex/values"
import { query } from "./_generated/server"
import { bookingStatus, organizationStatus } from "./domainValidators"

export const snapshot = query({
  args: { organizationPublicId: v.optional(v.string()) },
  returns: v.union(v.null(), v.object({
    organization: v.object({ id: v.string(), name: v.string(), status: organizationStatus, timezone: v.string() }),
    metrics: v.object({ todayBookings: v.number(), pendingConfirmation: v.number(), waitingNow: v.number(), upcomingWeek: v.number() }),
    upcoming: v.array(v.object({ id: v.string(), personName: v.string(), serviceName: v.string(), startsAt: v.number(), status: bookingStatus, mode: v.string() })),
    queue: v.array(v.object({ id: v.string(), ticketNumber: v.number(), personName: v.string(), serviceName: v.string(), checkedInAt: v.number(), priorityRank: v.number() })),
    pipeline: v.array(v.object({ provider: v.string(), state: v.string(), step: v.string(), updatedAt: v.number() })),
  })),
  handler: async (ctx, args) => {
    const identity = await ctx.auth.getUserIdentity()
    if (!identity) return null
    const principal = await ctx.db.query("principals").withIndex("by_external_subject", (q) => q.eq("externalSubject", identity.subject)).unique()
    let organization = args.organizationPublicId ? await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId!)).unique() : null
    if (!organization && principal?.organizationId) organization = await ctx.db.get(principal.organizationId)
    if (!organization) organization = await ctx.db.query("organizations").first()
    if (!organization || (principal?.organizationId && principal.organizationId !== organization._id)) return null
    const now = Date.now()
    const week = now + 7 * 24 * 60 * 60_000
    const bookings = await ctx.db.query("bookings").withIndex("by_organization_start", (q) => q.eq("organizationId", organization!._id).gte("startsAt", now - 24 * 60 * 60_000).lt("startsAt", week)).collect()
    const waiting = await ctx.db.query("queueEntries").withIndex("by_organization_status", (q) => q.eq("organizationId", organization!._id).eq("status", "waiting")).collect()
    const provisioning = await ctx.db.query("integrationProvisioning").filter((q) => q.eq(q.field("organizationId"), organization!._id)).collect()
    const localToday = new Intl.DateTimeFormat("en-CA", { timeZone: organization.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(now))
    const upcoming = await Promise.all(bookings.filter((item) => item.startsAt >= now).sort((a, b) => a.startsAt - b.startsAt).slice(0, 8).map(async (booking) => {
      const person = await ctx.db.get(booking.bookerPersonId)
      return { id: booking.publicId, personName: person?.fullName ?? "Persona", serviceName: booking.snapshot.serviceName, startsAt: booking.startsAt, status: booking.status, mode: booking.bookingMode }
    }))
    const queue = await Promise.all(waiting.sort((a, b) => a.priorityRank - b.priorityRank || a.checkInSequence - b.checkInSequence).slice(0, 10).map(async (entry) => {
      const person = await ctx.db.get(entry.personId)
      const service = await ctx.db.get(entry.serviceId)
      return { id: entry.publicId, ticketNumber: entry.ticketNumber, personName: person?.fullName ?? "Persona", serviceName: service?.name ?? "Servicio", checkedInAt: entry.checkedInAt, priorityRank: entry.priorityRank }
    }))
    return {
      organization: { id: organization.publicId, name: organization.name, status: organization.status, timezone: organization.timezone },
      metrics: { todayBookings: bookings.filter((item) => item.localDate === localToday).length, pendingConfirmation: bookings.filter((item) => item.status === "pending_confirmation").length, waitingNow: waiting.length, upcomingWeek: bookings.filter((item) => item.startsAt >= now).length },
      upcoming, queue,
      pipeline: provisioning.map((item) => ({ provider: item.provider, state: item.state, step: item.step, updatedAt: item.updatedAt })),
    }
  },
})

