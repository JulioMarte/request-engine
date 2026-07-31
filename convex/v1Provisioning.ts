import { v } from "convex/values"
import type { Id } from "./_generated/dataModel"
import { internalAction, internalMutation, internalQuery } from "./_generated/server"
import { internal } from "./_generated/api"
import { fail } from "./lib/errors"

declare const process: { env: Record<string, string | undefined> }

const provider = v.union(v.literal("chatwoot"), v.literal("evolution"), v.literal("n8n"), v.literal("meta_cloud"))
const state = v.union(v.literal("pending"), v.literal("in_progress"), v.literal("waiting_for_qr"), v.literal("connected"), v.literal("failed"))

export const context = internalQuery({
  args: { organizationPublicId: v.string() },
  returns: v.union(v.null(), v.object({ organizationId: v.id("organizations"), publicId: v.string(), name: v.string(), locale: v.string(), ownerEmail: v.string(), ownerPhoneE164: v.string() })),
  handler: async (ctx, args) => {
    const organization = await ctx.db.query("organizations").withIndex("by_public_id", (q) => q.eq("publicId", args.organizationPublicId)).unique()
    if (!organization) return null
    const onboarding = await ctx.db.query("onboardingSessions").withIndex("by_organization", (q) => q.eq("organizationId", organization._id)).first()
    if (!onboarding) return null
    return { organizationId: organization._id, publicId: organization.publicId, name: organization.name, locale: organization.locale, ownerEmail: onboarding.ownerEmail, ownerPhoneE164: onboarding.ownerPhoneE164 }
  },
})

export const getStep = internalQuery({
  args: { organizationId: v.id("organizations"), provider, step: v.string() },
  returns: v.union(v.null(), v.object({ id: v.id("integrationProvisioning"), externalAccountId: v.optional(v.string()), externalResourceId: v.optional(v.string()), encryptedCredential: v.optional(v.string()), encryptionKeyVersion: v.optional(v.number()), state, attempts: v.number() })),
  handler: async (ctx, args) => {
    const rows = await ctx.db.query("integrationProvisioning").withIndex("by_organization_provider", (q) => q.eq("organizationId", args.organizationId).eq("provider", args.provider)).collect()
    const row = rows.find((item) => item.step === args.step)
    return row ? { id: row._id, externalAccountId: row.externalAccountId, externalResourceId: row.externalResourceId, encryptedCredential: row.encryptedCredential, encryptionKeyVersion: row.encryptionKeyVersion, state: row.state, attempts: row.attempts } : null
  },
})

export const beginStep = internalMutation({
  args: { organizationId: v.id("organizations"), provider, step: v.string(), idempotencyKey: v.string() },
  returns: v.id("integrationProvisioning"),
  handler: async (ctx, args) => {
    const rows = await ctx.db.query("integrationProvisioning").withIndex("by_organization_provider", (q) => q.eq("organizationId", args.organizationId).eq("provider", args.provider)).collect()
    const existing = rows.find((item) => item.step === args.step)
    if (existing) {
      if (existing.state === "in_progress" && Date.now() - existing.updatedAt < 10 * 60_000) return existing._id
      await ctx.db.patch(existing._id, { state: "in_progress", attempts: existing.attempts + 1, lastError: undefined, updatedAt: Date.now() })
      return existing._id
    }
    const now = Date.now()
    return ctx.db.insert("integrationProvisioning", { organizationId: args.organizationId, provider: args.provider, step: args.step, idempotencyKey: args.idempotencyKey, state: "in_progress", attempts: 1, createdAt: now, updatedAt: now })
  },
})

export const finishStep = internalMutation({
  args: { id: v.id("integrationProvisioning"), state, externalAccountId: v.optional(v.string()), externalResourceId: v.optional(v.string()), encryptedCredential: v.optional(v.string()), encryptionKeyVersion: v.optional(v.number()), lastError: v.optional(v.string()) },
  returns: v.null(),
  handler: async (ctx, args) => {
    const { id, ...patch } = args
    await ctx.db.patch(id, { ...patch, updatedAt: Date.now() })
    return null
  },
})

async function requestJson(url: string, tokenHeader: string, token: string, payload: Record<string, unknown>) {
  const result = await fetch(url, { method: "POST", headers: { "content-type": "application/json", [tokenHeader]: token }, body: JSON.stringify(payload) })
  const text = await result.text()
  if (!result.ok) throw new Error(`HTTP ${result.status}: ${text.slice(0, 300)}`)
  return JSON.parse(text) as Record<string, unknown>
}

function bytesToBase64(bytes: Uint8Array) {
  let binary = ""
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function base64ToBytes(value: string) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0))
}

async function credentialKey() {
  const secret = process.env.PII_ENCRYPTION_KEY
  if (!secret) throw new Error("PII_ENCRYPTION_KEY is required to protect integration credentials")
  const raw = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(secret))
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"])
}

async function encryptCredential(value: string) {
  const iv = crypto.getRandomValues(new Uint8Array(12))
  const cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await credentialKey(), new TextEncoder().encode(value))
  return `${bytesToBase64(iv)}.${bytesToBase64(new Uint8Array(cipher))}`
}

async function decryptCredential(value: string) {
  const [iv, cipher] = value.split(".")
  const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: base64ToBytes(iv) }, await credentialKey(), base64ToBytes(cipher))
  return new TextDecoder().decode(clear)
}

export const runPilot = internalAction({
  args: { organizationPublicId: v.string(), whatsappNumber: v.string() },
  returns: v.object({ chatwootAccountId: v.string(), technicalUserId: v.string(), agentBotId: v.string(), evolutionInstance: v.string(), state: state, qrCode: v.optional(v.string()) }),
  handler: async (ctx, args): Promise<{ chatwootAccountId: string, technicalUserId: string, agentBotId: string, evolutionInstance: string, state: "waiting_for_qr" | "connected", qrCode?: string }> => {
    const context = await ctx.runQuery(internal.v1Provisioning.context, { organizationPublicId: args.organizationPublicId })
    if (!context) fail("NOT_FOUND", "Onboarding context not found")
    const chatwootUrl = process.env.CHATWOOT_BASE_URL?.replace(/\/$/, "")
    const platformToken = process.env.CHATWOOT_PLATFORM_TOKEN
    const evolutionUrl = process.env.EVOLUTION_BASE_URL?.replace(/\/$/, "")
    const evolutionToken = process.env.EVOLUTION_API_KEY
    const evolutionWebhookUrl = process.env.EVOLUTION_WEBHOOK_URL
    const n8nUrl = process.env.N8N_CHATWOOT_BOT_WEBHOOK_URL
    const technicalPassword = process.env.CHATWOOT_TECHNICAL_USER_PASSWORD
    const existingAccountId = process.env.CHATWOOT_EXISTING_ACCOUNT_ID
    const existingAdminToken = process.env.CHATWOOT_ADMIN_API_TOKEN
    if (!chatwootUrl || !platformToken || !evolutionUrl || !evolutionToken || !n8nUrl || (!existingAdminToken && !technicalPassword)) fail("INVALID_INPUT", "Chatwoot, Evolution, n8n and either an existing admin token or technical-user password must be configured")

    let account = await ctx.runQuery(internal.v1Provisioning.getStep, { organizationId: context.organizationId, provider: "chatwoot", step: "account" })
    if (!account?.externalResourceId) {
      const stepId: Id<"integrationProvisioning"> = await ctx.runMutation(internal.v1Provisioning.beginStep, { organizationId: context.organizationId, provider: "chatwoot", step: "account", idempotencyKey: `${context.publicId}:chatwoot:account` })
      try {
        const externalId = existingAccountId
          ? existingAccountId
          : String((await requestJson(`${chatwootUrl}/platform/api/v1/accounts`, "api_access_token", platformToken, { name: context.name, locale: context.locale.split("-")[0], support_email: context.ownerEmail, status: "active", limits: {}, custom_attributes: { request_engine_organization_id: context.publicId } })).id)
        await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: "connected", externalResourceId: externalId })
        account = { id: stepId, externalAccountId: undefined, externalResourceId: externalId, encryptedCredential: undefined, encryptionKeyVersion: undefined, state: "connected", attempts: 1 }
      } catch (error) {
        await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: "failed", lastError: error instanceof Error ? error.message : "Account provisioning failed" })
        throw error
      }
    }
    if (!account?.externalResourceId) fail("NOT_FOUND", "Chatwoot account provisioning did not return an ID")
    const accountId = account.externalResourceId

    let technical = await ctx.runQuery(internal.v1Provisioning.getStep, { organizationId: context.organizationId, provider: "chatwoot", step: "technical_user" })
    let technicalToken = technical?.encryptedCredential ? await decryptCredential(technical.encryptedCredential) : undefined
    if (!technical?.externalResourceId || !technicalToken) {
      const stepId: Id<"integrationProvisioning"> = await ctx.runMutation(internal.v1Provisioning.beginStep, { organizationId: context.organizationId, provider: "chatwoot", step: "technical_user", idempotencyKey: `${context.publicId}:chatwoot:technical_user` })
      try {
        let externalId = "existing-admin"
        if (existingAdminToken) {
          technicalToken = existingAdminToken
        } else {
          const safeName = context.publicId.replace(/[^a-zA-Z0-9]/g, "").slice(-18).toLocaleLowerCase()
          const created = await requestJson(`${chatwootUrl}/platform/api/v1/users`, "api_access_token", platformToken, { name: `${context.name} Automation`, display_name: "Agenda Bot", email: `request-engine+${safeName}@${new URL(chatwootUrl).hostname}`, password: technicalPassword!, custom_attributes: { request_engine_organization_id: context.publicId } })
          technicalToken = String(created.access_token)
          externalId = String(created.id)
          await requestJson(`${chatwootUrl}/platform/api/v1/accounts/${accountId}/account_users`, "api_access_token", platformToken, { user_id: Number(created.id), role: "administrator" })
        }
        await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: "connected", externalAccountId: accountId, externalResourceId: externalId, encryptedCredential: await encryptCredential(technicalToken), encryptionKeyVersion: 1 })
        technical = { id: stepId, externalAccountId: accountId, externalResourceId: externalId, encryptedCredential: "stored", encryptionKeyVersion: 1, state: "connected", attempts: 1 }
      } catch (error) {
        await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: "failed", lastError: error instanceof Error ? error.message : "Technical user provisioning failed" })
        throw error
      }
    }

    let bot = await ctx.runQuery(internal.v1Provisioning.getStep, { organizationId: context.organizationId, provider: "chatwoot", step: "agent_bot" })
    if (!bot?.externalResourceId) {
      const stepId: Id<"integrationProvisioning"> = await ctx.runMutation(internal.v1Provisioning.beginStep, { organizationId: context.organizationId, provider: "chatwoot", step: "agent_bot", idempotencyKey: `${context.publicId}:chatwoot:agent_bot` })
      const created = await requestJson(`${chatwootUrl}/platform/api/v1/agent_bots`, "api_access_token", platformToken, { name: `${context.name} Agenda`, description: "Request Engine scheduling agent", outgoing_url: n8nUrl, account_id: Number(accountId) })
      const externalId = String(created.id)
      await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: "connected", externalAccountId: accountId, externalResourceId: externalId })
      bot = { id: stepId, externalAccountId: accountId, externalResourceId: externalId, encryptedCredential: undefined, encryptionKeyVersion: undefined, state: "connected", attempts: 1 }
    }

    const instanceName = `re-${context.publicId.replace(/[^a-zA-Z0-9]/g, "").slice(-20).toLocaleLowerCase()}`
    let evolution = await ctx.runQuery(internal.v1Provisioning.getStep, { organizationId: context.organizationId, provider: "evolution", step: "baileys_instance" })
    let qrCode: string | undefined
    if (!evolution?.externalResourceId) {
      const stepId: Id<"integrationProvisioning"> = await ctx.runMutation(internal.v1Provisioning.beginStep, { organizationId: context.organizationId, provider: "evolution", step: "baileys_instance", idempotencyKey: `${context.publicId}:evolution:${instanceName}` })
      const created = await requestJson(`${evolutionUrl}/instance/create`, "apikey", evolutionToken, { instanceName, number: args.whatsappNumber, qrcode: true, integration: "WHATSAPP-BAILEYS", chatwootAccountId: accountId, chatwootToken: technicalToken, chatwootUrl, chatwootSignMsg: true, chatwootReopenConversation: true, chatwootConversationPending: false, chatwootImportContacts: true, chatwootImportMessages: false, chatwootDaysLimitImportMessages: 0, chatwootNameInbox: context.name, chatwootOrganization: context.name, webhook: evolutionWebhookUrl ? { enabled: true, url: evolutionWebhookUrl, events: ["QRCODE_UPDATED", "CONNECTION_UPDATE"] } : undefined })
      const qr = created.qrcode as Record<string, unknown> | undefined
      qrCode = typeof qr?.base64 === "string" ? qr.base64 : typeof created.qrcode === "string" ? created.qrcode : undefined
      await ctx.runMutation(internal.v1Provisioning.finishStep, { id: stepId, state: qrCode ? "waiting_for_qr" : "in_progress", externalAccountId: accountId, externalResourceId: instanceName })
      evolution = { id: stepId, externalAccountId: accountId, externalResourceId: instanceName, encryptedCredential: undefined, encryptionKeyVersion: undefined, state: qrCode ? "waiting_for_qr" : "in_progress", attempts: 1 }
    }
    if (!technical?.externalResourceId || !bot?.externalResourceId || !evolution?.externalResourceId) fail("NOT_FOUND", "Provisioning did not produce all required external IDs")
    return { chatwootAccountId: accountId, technicalUserId: technical.externalResourceId, agentBotId: bot.externalResourceId, evolutionInstance: evolution.externalResourceId, state: evolution.state === "connected" ? "connected" : "waiting_for_qr", qrCode }
  },
})

export const evolutionConnectionUpdate = internalMutation({
  args: { instanceName: v.string(), externalEventId: v.string(), connectionState: v.union(v.literal("open"), v.literal("close"), v.literal("connecting")), qrCode: v.optional(v.string()), payloadHash: v.string() },
  returns: v.object({ accepted: v.boolean(), organizationPublicId: v.optional(v.string()) }),
  handler: async (ctx, args) => {
    const duplicate = await ctx.db.query("webhookReceipts").withIndex("by_provider_event", (q) => q.eq("provider", "evolution").eq("externalEventId", args.externalEventId)).unique()
    if (duplicate) return { accepted: true }
    const row = await ctx.db.query("integrationProvisioning").withIndex("by_provider_external", (q) => q.eq("provider", "evolution").eq("externalResourceId", args.instanceName)).unique()
    if (!row) fail("NOT_FOUND", "Evolution instance is not registered")
    const organization = await ctx.db.get(row.organizationId)
    const now = Date.now()
    await ctx.db.insert("webhookReceipts", { provider: "evolution", externalEventId: args.externalEventId, eventType: "evolution.connection_update", organizationId: row.organizationId, payloadHash: args.payloadHash, status: "accepted", receivedAt: now, processedAt: now })
    await ctx.db.patch(row._id, { state: args.connectionState === "open" ? "connected" : args.qrCode ? "waiting_for_qr" : "in_progress", updatedAt: now })
    if (args.qrCode && organization) await ctx.db.insert("outboxEvents", { eventId: args.externalEventId, eventType: "integration.qr_code_updated", version: 1, organizationId: organization._id, aggregateType: "integration", aggregatePublicId: args.instanceName, payload: { qrCode: args.qrCode, provider: "evolution" }, status: "pending", attempts: 0, availableAt: now, occurredAt: now, updatedAt: now })
    return { accepted: true, organizationPublicId: organization?.publicId }
  },
})
