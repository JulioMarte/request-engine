import { v } from "convex/values"
import { mutation, query } from "./_generated/server"

export const list = query({
  args: {},
  returns: v.array(v.object({ _id: v.id("tenants"), _creationTime: v.number(), name: v.string(), businessType: v.string(), chatwootAccountId: v.number(), modules: v.array(v.string()), providers: v.object({ appointment: v.optional(v.string()), quote: v.optional(v.string()), catalog: v.optional(v.string()) }), isActive: v.boolean(), createdAt: v.number(), updatedAt: v.number() })),
  handler: async (ctx) => {
    return ctx.db.query("tenants").collect()
  },
})

export const getByChatwootAccount = query({
  args: { chatwootAccountId: v.number() },
  returns: v.union(v.null(), v.object({ _id: v.id("tenants"), _creationTime: v.number(), name: v.string(), businessType: v.string(), chatwootAccountId: v.number(), modules: v.array(v.string()), providers: v.object({ appointment: v.optional(v.string()), quote: v.optional(v.string()), catalog: v.optional(v.string()) }), isActive: v.boolean(), createdAt: v.number(), updatedAt: v.number() })),
  handler: async (ctx, args) => {
    return ctx.db
      .query("tenants")
      .withIndex("by_chatwoot_account", (q) => q.eq("chatwootAccountId", args.chatwootAccountId))
      .first()
  },
})

export const create = mutation({
  args: {
    name: v.string(),
    businessType: v.string(),
    chatwootAccountId: v.number(),
  },
  returns: v.id("tenants"),
  handler: async (ctx, args) => {
    const now = Date.now()
    return ctx.db.insert("tenants", {
      ...args,
      modules: ["information", "appointment", "quote"],
      providers: {
        appointment: "internal",
        quote: "internal",
        catalog: "internal",
      },
      isActive: true,
      createdAt: now,
      updatedAt: now,
    })
  },
})

export const update = mutation({
  args: {
    tenantId: v.id("tenants"),
    name: v.optional(v.string()),
    businessType: v.optional(v.string()),
    isActive: v.optional(v.boolean()),
  },
  returns: v.id("tenants"),
  handler: async (ctx, args) => {
    const { tenantId, ...patch } = args
    await ctx.db.patch(tenantId, { ...patch, updatedAt: Date.now() })
    return tenantId
  },
})
