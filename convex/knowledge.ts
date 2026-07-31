import { v } from "convex/values"
import { mutation, query } from "./_generated/server"

export const listByTenant = query({
  args: { tenantId: v.id("tenants") },
  returns: v.array(v.object({ _id: v.id("knowledgeItems"), _creationTime: v.number(), tenantId: v.id("tenants"), title: v.string(), content: v.string(), tags: v.array(v.string()), isActive: v.boolean(), category: v.optional(v.string()), priority: v.optional(v.number()), reviewedAt: v.optional(v.number()), status: v.optional(v.string()), type: v.optional(v.string()), updatedByUserId: v.optional(v.string()), visibility: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() })),
  handler: async (ctx, args) => {
    return ctx.db
      .query("knowledgeItems")
      .withIndex("by_tenant", (q) => q.eq("tenantId", args.tenantId))
      .collect()
  },
})

export const create = mutation({
  args: {
    tenantId: v.id("tenants"),
    title: v.string(),
    content: v.string(),
    tags: v.optional(v.array(v.string())),
  },
  returns: v.id("knowledgeItems"),
  handler: async (ctx, args) => {
    const now = Date.now()
    return ctx.db.insert("knowledgeItems", {
      ...args,
      tags: args.tags ?? [],
      isActive: true,
      createdAt: now,
      updatedAt: now,
    })
  },
})

export const update = mutation({
  args: {
    knowledgeItemId: v.id("knowledgeItems"),
    title: v.optional(v.string()),
    content: v.optional(v.string()),
    tags: v.optional(v.array(v.string())),
    isActive: v.optional(v.boolean()),
  },
  returns: v.id("knowledgeItems"),
  handler: async (ctx, args) => {
    const { knowledgeItemId, ...patch } = args
    await ctx.db.patch(knowledgeItemId, { ...patch, updatedAt: Date.now() })
    return knowledgeItemId
  },
})
