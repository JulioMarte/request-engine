import { v } from "convex/values"
import { mutation, query } from "./_generated/server"

const aiMode = v.union(
  v.literal("auto"),
  v.literal("manual"),
  v.literal("handoff"),
  v.literal("paused"),
  v.literal("disabled"),
)

export const getByConversation = query({
  args: {
    chatwootAccountId: v.number(),
    chatwootConversationId: v.number(),
  },
  handler: async (ctx, args) => {
    return ctx.db
      .query("aiStates")
      .withIndex("by_conversation", (q) =>
        q
          .eq("chatwootAccountId", args.chatwootAccountId)
          .eq("chatwootConversationId", args.chatwootConversationId),
      )
      .first()
  },
})

export const setMode = mutation({
  args: {
    tenantId: v.id("tenants"),
    channelId: v.optional(v.id("channels")),
    chatwootAccountId: v.number(),
    chatwootConversationId: v.number(),
    mode: aiMode,
    lastSummary: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    const existing = await ctx.db
      .query("aiStates")
      .withIndex("by_conversation", (q) =>
        q
          .eq("chatwootAccountId", args.chatwootAccountId)
          .eq("chatwootConversationId", args.chatwootConversationId),
      )
      .first()

    const now = Date.now()
    const patch = {
      tenantId: args.tenantId,
      channelId: args.channelId,
      chatwootAccountId: args.chatwootAccountId,
      chatwootConversationId: args.chatwootConversationId,
      mode: args.mode,
      lastSummary: args.lastSummary,
      lastEvent: `AI mode changed to ${args.mode}`,
      updatedAt: now,
    }

    if (existing) {
      await ctx.db.patch(existing._id, patch)
      return existing._id
    }

    return ctx.db.insert("aiStates", {
      ...patch,
      createdAt: now,
    })
  },
})
