import { v } from "convex/values"
import { internalAction, internalMutation, internalQuery } from "./_generated/server"
import { internal } from "./_generated/api"
import type { Id } from "./_generated/dataModel"

declare const process: { env: Record<string, string | undefined> }

export const due = internalQuery({
  args: { limit: v.number() },
  returns: v.array(v.object({ id: v.id("outboxEvents"), eventId: v.string(), eventType: v.string(), version: v.number(), organizationPublicId: v.string(), aggregatePublicId: v.string(), payload: v.record(v.string(), v.union(v.string(), v.number(), v.boolean(), v.null())), occurredAt: v.number(), attempts: v.number() })),
  handler: async (ctx, args) => {
    const items = await ctx.db.query("outboxEvents").withIndex("by_status_available", (q) => q.eq("status", "pending").lte("availableAt", Date.now())).take(Math.min(args.limit, 50))
    return Promise.all(items.map(async (item) => {
      const organization = await ctx.db.get(item.organizationId)
      return { id: item._id, eventId: item.eventId, eventType: item.eventType, version: item.version, organizationPublicId: organization?.publicId ?? "unknown", aggregatePublicId: item.aggregatePublicId, payload: item.payload, occurredAt: item.occurredAt, attempts: item.attempts }
    }))
  },
})

export const finish = internalMutation({
  args: { id: v.id("outboxEvents"), delivered: v.boolean(), error: v.optional(v.string()) },
  returns: v.null(),
  handler: async (ctx, args) => {
    const item = await ctx.db.get(args.id)
    if (!item || item.status === "delivered") return null
    const attempts = item.attempts + 1
    await ctx.db.patch(item._id, { status: args.delivered ? "delivered" : attempts >= 8 ? "failed" : "pending", attempts, availableAt: args.delivered ? item.availableAt : Date.now() + Math.min(60, 2 ** attempts) * 60_000, lastError: args.error, updatedAt: Date.now() })
    return null
  },
})

export const dispatch = internalAction({
  args: {},
  returns: v.object({ processed: v.number(), delivered: v.number() }),
  handler: async (ctx): Promise<{ processed: number, delivered: number }> => {
    const url = process.env.N8N_OUTBOX_WEBHOOK_URL
    const secret = process.env.N8N_OUTBOX_WEBHOOK_SECRET
    if (!url || !secret) return { processed: 0, delivered: 0 }
    const events: Array<{ id: Id<"outboxEvents">, eventId: string, eventType: string, version: number, organizationPublicId: string, aggregatePublicId: string, payload: Record<string, string | number | boolean | null>, occurredAt: number, attempts: number }> = await ctx.runQuery(internal.v1Outbox.due, { limit: 25 })
    let delivered = 0
    for (const event of events) {
      const envelope = { eventId: event.eventId, eventType: event.eventType, version: event.version, organizationId: event.organizationPublicId, aggregateId: event.aggregatePublicId, occurredAt: new Date(event.occurredAt).toISOString(), payload: event.payload }
      const raw = JSON.stringify(envelope)
      const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"])
      const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(raw))
      const hex = Array.from(new Uint8Array(signature)).map((byte) => byte.toString(16).padStart(2, "0")).join("")
      try {
        const result = await fetch(url, { method: "POST", headers: { "content-type": "application/json", "x-request-engine-signature": `sha256=${hex}` }, body: raw })
        await ctx.runMutation(internal.v1Outbox.finish, { id: event.id, delivered: result.ok, error: result.ok ? undefined : `HTTP ${result.status}` })
        if (result.ok) delivered += 1
      } catch (error) {
        await ctx.runMutation(internal.v1Outbox.finish, { id: event.id, delivered: false, error: error instanceof Error ? error.message : "Network error" })
      }
    }
    return { processed: events.length, delivered }
  },
})
