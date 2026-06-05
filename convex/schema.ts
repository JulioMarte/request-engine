import { defineSchema, defineTable } from "convex/server"
import { v } from "convex/values"

const aiMode = v.union(
  v.literal("auto"),
  v.literal("manual"),
  v.literal("handoff"),
  v.literal("paused"),
  v.literal("disabled"),
)

const catalogType = v.union(
  v.literal("service"),
  v.literal("product"),
  v.literal("package"),
  v.literal("asset"),
  v.literal("custom"),
)

const fulfillmentType = v.union(
  v.literal("information"),
  v.literal("appointment"),
  v.literal("quote"),
  v.literal("handoff"),
)

const requestStatus = v.union(
  v.literal("new"),
  v.literal("detected"),
  v.literal("collecting_info"),
  v.literal("ready_to_process"),
  v.literal("processing"),
  v.literal("waiting_confirmation"),
  v.literal("completed"),
  v.literal("failed"),
  v.literal("handoff"),
  v.literal("cancelled"),
)

export default defineSchema({
  tenants: defineTable({
    name: v.string(),
    businessType: v.string(),
    chatwootAccountId: v.number(),
    modules: v.array(v.string()),
    providers: v.object({
      appointment: v.optional(v.string()),
      quote: v.optional(v.string()),
      catalog: v.optional(v.string()),
    }),
    isActive: v.boolean(),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_chatwoot_account", ["chatwootAccountId"]),

  channels: defineTable({
    tenantId: v.id("tenants"),
    chatwootAccountId: v.number(),
    chatwootInboxId: v.number(),
    displayName: v.string(),
    isActive: v.boolean(),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_chatwoot_inbox", ["chatwootAccountId", "chatwootInboxId"]),

  aiStates: defineTable({
    tenantId: v.id("tenants"),
    channelId: v.optional(v.id("channels")),
    chatwootAccountId: v.number(),
    chatwootConversationId: v.number(),
    mode: aiMode,
    lastSummary: v.optional(v.string()),
    lastEvent: v.optional(v.string()),
    pausedUntil: v.optional(v.number()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_conversation", ["chatwootAccountId", "chatwootConversationId"]),

  catalogItems: defineTable({
    tenantId: v.id("tenants"),
    name: v.string(),
    description: v.string(),
    type: catalogType,
    synonyms: v.array(v.string()),
    fulfillmentType,
    basePrice: v.optional(v.number()),
    durationMinutes: v.optional(v.number()),
    isActive: v.boolean(),
    metadata: v.optional(v.any()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_tenant", ["tenantId"]),

  knowledgeItems: defineTable({
    tenantId: v.id("tenants"),
    title: v.string(),
    content: v.string(),
    tags: v.array(v.string()),
    isActive: v.boolean(),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_tenant", ["tenantId"]),

  requests: defineTable({
    tenantId: v.id("tenants"),
    chatwootAccountId: v.number(),
    chatwootConversationId: v.number(),
    chatwootContactId: v.optional(v.number()),
    intent: v.string(),
    catalogItemId: v.optional(v.id("catalogItems")),
    status: requestStatus,
    collectedFields: v.any(),
    missingFields: v.array(v.string()),
    nextAction: v.optional(v.string()),
    confidence: v.optional(v.number()),
    summary: v.optional(v.string()),
    createdAt: v.number(),
    updatedAt: v.number(),
  })
    .index("by_conversation", ["chatwootAccountId", "chatwootConversationId"])
    .index("by_tenant_status", ["tenantId", "status"]),

  requestEvents: defineTable({
    tenantId: v.id("tenants"),
    requestId: v.id("requests"),
    eventType: v.string(),
    payload: v.any(),
    actor: v.union(
      v.literal("system"),
      v.literal("ai"),
      v.literal("human"),
      v.literal("webhook"),
      v.literal("integration"),
    ),
    createdAt: v.number(),
  }).index("by_request", ["requestId"]),

  appointments: defineTable({
    tenantId: v.id("tenants"),
    requestId: v.id("requests"),
    contactInfo: v.any(),
    catalogItemId: v.optional(v.id("catalogItems")),
    startsAt: v.number(),
    endsAt: v.number(),
    status: v.union(
      v.literal("pending_confirmation"),
      v.literal("confirmed"),
      v.literal("rescheduled"),
      v.literal("cancelled"),
      v.literal("completed"),
      v.literal("no_show"),
    ),
    location: v.optional(v.string()),
    staffId: v.optional(v.string()),
    sourceConversationId: v.number(),
    notes: v.optional(v.string()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_tenant_start", ["tenantId", "startsAt"]),

  quotes: defineTable({
    tenantId: v.id("tenants"),
    requestId: v.id("requests"),
    customerInfo: v.any(),
    quoteNumber: v.string(),
    status: v.union(
      v.literal("draft"),
      v.literal("sent"),
      v.literal("accepted"),
      v.literal("rejected"),
      v.literal("expired"),
      v.literal("cancelled"),
    ),
    items: v.array(v.any()),
    subtotal: v.number(),
    taxes: v.optional(v.number()),
    total: v.number(),
    externalId: v.optional(v.string()),
    provider: v.string(),
    publicUrl: v.optional(v.string()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_tenant_status", ["tenantId", "status"]),

  integrationConnections: defineTable({
    tenantId: v.id("tenants"),
    type: v.union(
      v.literal("internal"),
      v.literal("n8n_webhook"),
      v.literal("odoo"),
      v.literal("erpnext"),
      v.literal("google_calendar"),
      v.literal("custom_api"),
    ),
    name: v.string(),
    config: v.any(),
    isActive: v.boolean(),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_tenant", ["tenantId"]),

  webhookEvents: defineTable({
    tenantId: v.optional(v.id("tenants")),
    chatwootAccountId: v.optional(v.number()),
    eventKey: v.string(),
    eventType: v.string(),
    payload: v.any(),
    status: v.union(v.literal("received"), v.literal("processed"), v.literal("ignored"), v.literal("failed")),
    error: v.optional(v.string()),
    createdAt: v.number(),
    updatedAt: v.number(),
  }).index("by_event_key", ["eventKey"]),
})
