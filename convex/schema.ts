import { defineSchema, defineTable } from "convex/server"
import { v } from "convex/values"
import {
  bookingMode,
  bookingStatus,
  channel,
  membershipRole,
  modality,
  organizationStatus,
  price,
  principalType,
  requiredField,
  shift,
  structuredRecord,
} from "./domainValidators"

const legacyActor = v.union(v.literal("system"), v.literal("ai"), v.literal("human"), v.literal("webhook"), v.literal("integration"))
const auditActor = v.object({ principalId: v.optional(v.id("principals")), type: principalType, label: v.optional(v.string()) })

export default defineSchema({
  // Legacy prototype. Kept readable during the verified migration to v1.
  tenants: defineTable({
    name: v.string(), businessType: v.string(), chatwootAccountId: v.number(), modules: v.array(v.string()),
    providers: v.object({ appointment: v.optional(v.string()), quote: v.optional(v.string()), catalog: v.optional(v.string()) }),
    isActive: v.boolean(), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_chatwoot_account", ["chatwootAccountId"]),
  channels: defineTable({
    tenantId: v.id("tenants"), chatwootAccountId: v.number(), chatwootInboxId: v.number(), displayName: v.string(),
    isActive: v.boolean(), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_chatwoot_inbox", ["chatwootAccountId", "chatwootInboxId"]),
  aiStates: defineTable({
    tenantId: v.id("tenants"), channelId: v.optional(v.id("channels")), chatwootAccountId: v.number(),
    chatwootConversationId: v.number(), mode: v.union(v.literal("auto"), v.literal("manual"), v.literal("handoff"), v.literal("paused"), v.literal("disabled")),
    lastSummary: v.optional(v.string()), lastEvent: v.optional(v.string()), pausedUntil: v.optional(v.number()), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_conversation", ["chatwootAccountId", "chatwootConversationId"]),
  catalogItems: defineTable({
    tenantId: v.id("tenants"), name: v.string(), description: v.string(),
    type: v.union(v.literal("service"), v.literal("product"), v.literal("package"), v.literal("asset"), v.literal("custom")),
    synonyms: v.array(v.string()), fulfillmentType: v.union(v.literal("information"), v.literal("appointment"), v.literal("quote"), v.literal("handoff")),
    basePrice: v.optional(v.number()), durationMinutes: v.optional(v.number()), isActive: v.boolean(), metadata: v.optional(structuredRecord), createdAt: v.number(), updatedAt: v.number(),
    currency: v.optional(v.string()), sku: v.optional(v.string()), source: v.optional(v.string()), taxRate: v.optional(v.number()), unit: v.optional(v.string()),
  }).index("by_tenant", ["tenantId"]),
  knowledgeItems: defineTable({ tenantId: v.id("tenants"), title: v.string(), content: v.string(), tags: v.array(v.string()), isActive: v.boolean(), category: v.optional(v.string()), priority: v.optional(v.number()), reviewedAt: v.optional(v.number()), status: v.optional(v.string()), type: v.optional(v.string()), updatedByUserId: v.optional(v.string()), visibility: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() }).index("by_tenant", ["tenantId"]),
  requests: defineTable({
    tenantId: v.id("tenants"), chatwootAccountId: v.number(), chatwootConversationId: v.number(), chatwootContactId: v.optional(v.number()), intent: v.string(),
    catalogItemId: v.optional(v.id("catalogItems")), status: v.union(v.literal("new"), v.literal("detected"), v.literal("collecting_info"), v.literal("ready_to_process"), v.literal("processing"), v.literal("waiting_confirmation"), v.literal("completed"), v.literal("failed"), v.literal("handoff"), v.literal("cancelled")),
    collectedFields: structuredRecord, missingFields: v.array(v.string()), nextAction: v.optional(v.string()), confidence: v.optional(v.number()), summary: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_conversation", ["chatwootAccountId", "chatwootConversationId"]).index("by_tenant_status", ["tenantId", "status"]),
  requestEvents: defineTable({ tenantId: v.id("tenants"), requestId: v.id("requests"), eventType: v.string(), payload: structuredRecord, actor: legacyActor, createdAt: v.number() }).index("by_request", ["requestId"]),
  appointments: defineTable({
    tenantId: v.id("tenants"), requestId: v.id("requests"), contactInfo: structuredRecord, catalogItemId: v.optional(v.id("catalogItems")), startsAt: v.number(), endsAt: v.number(),
    status: v.union(v.literal("pending_confirmation"), v.literal("confirmed"), v.literal("rescheduled"), v.literal("cancelled"), v.literal("completed"), v.literal("no_show")),
    location: v.optional(v.string()), staffId: v.optional(v.string()), sourceConversationId: v.number(), notes: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_tenant_start", ["tenantId", "startsAt"]),
  quotes: defineTable({
    tenantId: v.id("tenants"), requestId: v.optional(v.id("requests")), customerInfo: structuredRecord, quoteNumber: v.string(),
    status: v.union(v.literal("draft"), v.literal("sent"), v.literal("accepted"), v.literal("rejected"), v.literal("expired"), v.literal("cancelled")),
    items: v.optional(v.array(v.object({ name: v.string(), quantity: v.number(), amountMinor: v.number() }))), subtotal: v.number(), taxes: v.optional(v.number()), total: v.number(), externalId: v.optional(v.string()), provider: v.string(), publicUrl: v.optional(v.string()),
    chatwootAccountId: v.optional(v.number()), chatwootContactId: v.optional(v.number()), chatwootConversationId: v.optional(v.number()), createdByUserId: v.optional(v.string()), sentByUserId: v.optional(v.string()), currency: v.optional(v.string()), discountTotal: v.optional(v.number()), taxTotal: v.optional(v.number()), source: v.optional(v.string()), supersededByQuoteId: v.optional(v.string()), revisionNumber: v.optional(v.number()), revisionOfQuoteId: v.optional(v.string()), validUntil: v.optional(v.number()),
    createdAt: v.number(), updatedAt: v.number(),
  }).index("by_tenant_status", ["tenantId", "status"]),
  integrationConnections: defineTable({
    tenantId: v.id("tenants"), type: v.union(v.literal("internal"), v.literal("n8n_webhook"), v.literal("odoo"), v.literal("erpnext"), v.literal("google_calendar"), v.literal("custom_api")),
    name: v.string(), config: structuredRecord, isActive: v.boolean(), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_tenant", ["tenantId"]),
  webhookEvents: defineTable({ tenantId: v.optional(v.id("tenants")), chatwootAccountId: v.optional(v.number()), eventKey: v.string(), eventType: v.string(), payload: structuredRecord, status: v.union(v.literal("received"), v.literal("processed"), v.literal("ignored"), v.literal("failed")), error: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() }).index("by_event_key", ["eventKey"]),

  // Identity and tenancy.
  organizations: defineTable({
    publicId: v.string(), name: v.string(), legalName: v.optional(v.string()), industry: v.string(), countryCode: v.string(),
    timezone: v.string(), locale: v.string(), status: organizationStatus, holidayMentionEnabled: v.boolean(),
    createdAt: v.number(), updatedAt: v.number(), publishedAt: v.optional(v.number()),
  }).index("by_public_id", ["publicId"]).index("by_status", ["status"]),
  locations: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), name: v.string(), terminology: v.string(), timezone: v.string(), countryCode: v.string(), subdivisionCode: v.optional(v.string()),
    address: v.optional(v.object({ line1: v.string(), line2: v.optional(v.string()), city: v.string(), postalCode: v.optional(v.string()) })),
    status: v.union(v.literal("active"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization", ["organizationId"]),
  people: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), fullName: v.string(), dateOfBirth: v.optional(v.string()), preferredLocale: v.optional(v.string()),
    email: v.optional(v.string()), phoneE164: v.optional(v.string()), status: v.union(v.literal("active"), v.literal("archived")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization_phone", ["organizationId", "phoneE164"]),
  personIdentifiers: defineTable({
    organizationId: v.id("organizations"), personId: v.id("people"), type: v.union(v.literal("national_id"), v.literal("passport"), v.literal("driver_license"), v.literal("other")),
    countryCode: v.string(), encryptedValue: v.string(), blindHash: v.string(), maskedValue: v.string(), encryptionKeyVersion: v.number(), verifiedAt: v.optional(v.number()), createdAt: v.number(),
  }).index("by_organization_hash", ["organizationId", "blindHash"]).index("by_person", ["personId"]),
  personRelationships: defineTable({
    organizationId: v.id("organizations"), fromPersonId: v.id("people"), toPersonId: v.id("people"),
    type: v.union(v.literal("legal_guardian"), v.literal("parent"), v.literal("spouse"), v.literal("dependent"), v.literal("emergency_contact"), v.literal("other")),
    canBook: v.boolean(), startsOn: v.optional(v.string()), endsOn: v.optional(v.string()), createdAt: v.number(),
  }).index("by_from", ["fromPersonId"]).index("by_to", ["toPersonId"]),
  memberships: defineTable({ organizationId: v.id("organizations"), personId: v.id("people"), role: membershipRole, resourceId: v.optional(v.id("resources")), status: v.union(v.literal("invited"), v.literal("active"), v.literal("disabled")), createdAt: v.number(), updatedAt: v.number() }).index("by_organization", ["organizationId"]).index("by_person", ["personId"]),

  // Insurance and professional credentials. No claims or clinical records.
  payers: defineTable({ publicId: v.string(), countryCode: v.string(), name: v.string(), shortName: v.string(), status: v.union(v.literal("active"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number() }).index("by_country", ["countryCode"]).index("by_public_id", ["publicId"]),
  insurancePlans: defineTable({ publicId: v.string(), payerId: v.id("payers"), name: v.string(), planCode: v.optional(v.string()), status: v.union(v.literal("active"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number() }).index("by_payer", ["payerId"]),
  insuranceCoverages: defineTable({
    organizationId: v.id("organizations"), personId: v.id("people"), payerId: v.id("payers"), planId: v.optional(v.id("insurancePlans")),
    memberNumberEncrypted: v.string(), memberNumberBlindHash: v.string(), memberNumberMasked: v.string(), encryptionKeyVersion: v.number(),
    policyHolderPersonId: v.optional(v.id("people")), validFrom: v.optional(v.string()), validThrough: v.optional(v.string()), status: v.union(v.literal("unverified"), v.literal("verified"), v.literal("expired"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_person", ["personId"]).index("by_organization_hash", ["organizationId", "memberNumberBlindHash"]),
  providerCredentials: defineTable({
    organizationId: v.id("organizations"), personId: v.id("people"), type: v.union(v.literal("exequatur"), v.literal("professional_license"), v.literal("board_certification"), v.literal("other")),
    countryCode: v.string(), issuer: v.string(), valueEncrypted: v.string(), valueMasked: v.string(), blindHash: v.string(), encryptionKeyVersion: v.number(), validThrough: v.optional(v.string()), status: v.union(v.literal("unverified"), v.literal("verified"), v.literal("expired")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_person", ["personId"]).index("by_organization_hash", ["organizationId", "blindHash"]),

  // Catalog, resources and operating calendars.
  services: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), name: v.string(), description: v.string(), synonyms: v.array(v.string()), bookingMode, modalities: v.array(modality),
    durationMinutes: v.number(), slotIntervalMinutes: v.number(), bufferBeforeMinutes: v.number(), bufferAfterMinutes: v.number(), capacity: v.number(), price,
    requiredFields: v.array(requiredField), seriesEnrollment: v.union(v.literal("occurrence"), v.literal("series"), v.literal("both")),
    virtualProvider: v.union(v.literal("manual_link"), v.literal("adapter_pending")), virtualLink: v.optional(v.string()),
    autoReleaseUnconfirmed: v.boolean(), neverAutoCancel: v.boolean(), waitlistEnabled: v.boolean(), status: v.union(v.literal("draft"), v.literal("active"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization_status", ["organizationId", "status"]),
  resources: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), locationId: v.optional(v.id("locations")), name: v.string(),
    type: v.union(v.literal("staff"), v.literal("room"), v.literal("equipment"), v.literal("vehicle"), v.literal("other")), capacity: v.number(), personId: v.optional(v.id("people")),
    status: v.union(v.literal("active"), v.literal("inactive")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization", ["organizationId"]).index("by_location", ["locationId"]),
  serviceResourceRequirements: defineTable({ organizationId: v.id("organizations"), serviceId: v.id("services"), resourceType: v.union(v.literal("staff"), v.literal("room"), v.literal("equipment"), v.literal("vehicle"), v.literal("other")), quantity: v.number(), allowedResourceIds: v.array(v.id("resources")), required: v.boolean() }).index("by_service", ["serviceId"]),
  calendars: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), name: v.string(), timezone: v.string(), ownerType: v.union(v.literal("organization"), v.literal("location"), v.literal("service"), v.literal("resource")), locationId: v.optional(v.id("locations")), serviceId: v.optional(v.id("services")), resourceId: v.optional(v.id("resources")), createdAt: v.number(), updatedAt: v.number() }).index("by_organization", ["organizationId"]).index("by_service", ["serviceId"]).index("by_resource", ["resourceId"]),
  weeklyScheduleRules: defineTable({ organizationId: v.id("organizations"), calendarId: v.id("calendars"), weekday: v.number(), startMinute: v.number(), endMinute: v.number(), shift, effectiveFrom: v.optional(v.string()), effectiveThrough: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() }).index("by_calendar_weekday", ["calendarId", "weekday"]),
  scheduleExceptions: defineTable({ organizationId: v.id("organizations"), calendarId: v.id("calendars"), localDate: v.string(), type: v.union(v.literal("closed"), v.literal("open"), v.literal("custom_hours")), windows: v.array(v.object({ startMinute: v.number(), endMinute: v.number(), shift })), reason: v.string(), createdAt: v.number(), updatedAt: v.number() }).index("by_calendar_date", ["calendarId", "localDate"]),
  holidayOccurrences: defineTable({ publicId: v.string(), countryCode: v.string(), subdivisionCode: v.optional(v.string()), localDate: v.string(), observedDate: v.optional(v.string()), name: v.string(), sourceUrl: v.string(), fetchedAt: v.number(), reviewStatus: v.union(v.literal("pending"), v.literal("confirmed"), v.literal("rejected")), createdAt: v.number(), updatedAt: v.number() }).index("by_public_id", ["publicId"]).index("by_country_date", ["countryCode", "localDate"]),
  holidayReviews: defineTable({ organizationId: v.id("organizations"), locationId: v.id("locations"), holidayId: v.id("holidayOccurrences"), decision: v.union(v.literal("pending"), v.literal("open"), v.literal("closed"), v.literal("custom_hours")), windows: v.array(v.object({ startMinute: v.number(), endMinute: v.number() })), decidedBy: v.optional(v.id("principals")), decidedAt: v.optional(v.number()), createdAt: v.number(), updatedAt: v.number() }).index("by_location_holiday", ["locationId", "holidayId"]),

  // Availability and bookings.
  serviceSessions: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), serviceId: v.id("services"), locationId: v.optional(v.id("locations")), seriesId: v.optional(v.id("sessionSeries")),
    startsAt: v.number(), endsAt: v.number(), localDate: v.string(), timezone: v.string(), capacity: v.number(), reservedCount: v.number(), resourceIds: v.array(v.id("resources")),
    status: v.union(v.literal("scheduled"), v.literal("cancelled"), v.literal("completed")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_service_start", ["serviceId", "startsAt"]).index("by_organization_start", ["organizationId", "startsAt"]),
  sessionSeries: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), serviceId: v.id("services"), name: v.string(), timezone: v.string(), recurrenceRule: v.string(), startsOn: v.string(), endsOn: v.optional(v.string()), enrollmentMode: v.union(v.literal("occurrence"), v.literal("series"), v.literal("both")), status: v.union(v.literal("draft"), v.literal("active"), v.literal("ended")), createdAt: v.number(), updatedAt: v.number() }).index("by_service", ["serviceId"]),
  availabilityOffers: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), serviceId: v.id("services"), locationId: v.optional(v.id("locations")), sessionId: v.optional(v.id("serviceSessions")),
    bookingMode, startsAt: v.number(), endsAt: v.number(), localDate: v.string(), timezone: v.string(), shift: v.optional(shift), resourceIds: v.array(v.id("resources")),
    capacityUnits: v.number(), snapshot: v.object({ serviceName: v.string(), durationMinutes: v.number(), modality, price }),
    expiresAt: v.number(), consumedAt: v.optional(v.number()), createdAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization_expiry", ["organizationId", "expiresAt"]),
  bookings: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), serviceId: v.id("services"), locationId: v.optional(v.id("locations")), sessionId: v.optional(v.id("serviceSessions")),
    bookerPersonId: v.id("people"), status: bookingStatus, bookingMode, modality, startsAt: v.number(), endsAt: v.number(), localDate: v.string(), timezone: v.string(), shift: v.optional(shift),
    capacityUnits: v.number(), snapshot: v.object({ serviceName: v.string(), durationMinutes: v.number(), bufferBeforeMinutes: v.number(), bufferAfterMinutes: v.number(), locationName: v.optional(v.string()), price }),
    confirmationDeadlineAt: v.optional(v.number()), patientWarnedAboutAutoRelease: v.boolean(), seriesId: v.optional(v.id("sessionSeries")), previousBookingId: v.optional(v.id("bookings")),
    source: v.union(v.literal("agent"), v.literal("panel"), v.literal("api"), v.literal("walk_in")), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization_start", ["organizationId", "startsAt"]).index("by_person_start", ["bookerPersonId", "startsAt"]).index("by_status_deadline", ["status", "confirmationDeadlineAt"]),
  bookingParticipants: defineTable({ organizationId: v.id("organizations"), bookingId: v.id("bookings"), personId: v.id("people"), role: v.union(v.literal("attendee"), v.literal("patient"), v.literal("guardian"), v.literal("booker")), coverageId: v.optional(v.id("insuranceCoverages")), status: v.union(v.literal("registered"), v.literal("cancelled"), v.literal("attended"), v.literal("no_show")), createdAt: v.number(), updatedAt: v.number() }).index("by_booking", ["bookingId"]).index("by_person", ["personId"]),
  bookingAllocations: defineTable({ organizationId: v.id("organizations"), bookingId: v.id("bookings"), resourceId: v.id("resources"), localDate: v.string(), startsAt: v.number(), endsAt: v.number(), status: v.union(v.literal("held"), v.literal("released")), createdAt: v.number(), updatedAt: v.number() }).index("by_resource_date_start", ["resourceId", "localDate", "startsAt"]).index("by_booking", ["bookingId"]),
  bookingEvents: defineTable({ organizationId: v.id("organizations"), bookingId: v.id("bookings"), eventType: v.string(), fromStatus: v.optional(bookingStatus), toStatus: v.optional(bookingStatus), actor: auditActor, reason: v.optional(v.string()), data: structuredRecord, occurredAt: v.number() }).index("by_booking", ["bookingId"]),
  idempotencyKeys: defineTable({ organizationId: v.id("organizations"), principalId: v.id("principals"), operation: v.string(), key: v.string(), requestHash: v.string(), resourceType: v.string(), resourcePublicId: v.string(), response: structuredRecord, expiresAt: v.number(), createdAt: v.number() }).index("by_scope_key", ["organizationId", "principalId", "operation", "key"]),

  // Arrival queues and waitlists.
  queueEntries: defineTable({
    publicId: v.string(), organizationId: v.id("organizations"), bookingId: v.optional(v.id("bookings")), serviceId: v.id("services"), locationId: v.id("locations"), localDate: v.string(), shift,
    personId: v.id("people"), ticketNumber: v.number(), checkInSequence: v.number(), priorityRank: v.number(), priorityReason: v.optional(v.string()), prioritizedBy: v.optional(v.id("principals")),
    qrTokenHash: v.string(), qrTokenExpiresAt: v.number(), status: v.union(v.literal("waiting"), v.literal("called"), v.literal("in_service"), v.literal("completed"), v.literal("left")),
    checkedInAt: v.number(), calledAt: v.optional(v.number()), serviceStartedAt: v.optional(v.number()), completedAt: v.optional(v.number()), createdAt: v.number(), updatedAt: v.number(),
  }).index("by_public_id", ["publicId"]).index("by_organization_status", ["organizationId", "status"]).index("by_queue_order", ["locationId", "localDate", "shift", "status", "priorityRank", "checkInSequence"]).index("by_booking", ["bookingId"]),
  queueCounters: defineTable({ locationId: v.id("locations"), localDate: v.string(), shift, lastTicketNumber: v.number(), lastSequence: v.number(), updatedAt: v.number() }).index("by_window", ["locationId", "localDate", "shift"]),
  waitlistEntries: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), serviceId: v.id("services"), locationId: v.optional(v.id("locations")), personId: v.id("people"), preferredDates: v.array(v.string()), preferredShifts: v.array(shift), modality: v.optional(modality), warnedAutoRelease: v.boolean(), status: v.union(v.literal("waiting"), v.literal("offered"), v.literal("booked"), v.literal("expired"), v.literal("withdrawn")), priority: v.number(), createdAt: v.number(), updatedAt: v.number() }).index("by_service_status", ["serviceId", "status", "priority"]).index("by_person_service_status", ["personId", "serviceId", "status"]),
  waitlistOffers: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), entryId: v.id("waitlistEntries"), availabilityOfferId: v.id("availabilityOffers"), strategy: v.union(v.literal("sequential"), v.literal("small_batch")), status: v.union(v.literal("pending"), v.literal("accepted"), v.literal("declined"), v.literal("expired"), v.literal("lost")), expiresAt: v.number(), acceptedAt: v.optional(v.number()), createdAt: v.number(), updatedAt: v.number() }).index("by_public_id", ["publicId"]).index("by_availability_status", ["availabilityOfferId", "status"]),

  // Agent auth, prompts, outbox and integrations.
  principals: defineTable({ publicId: v.string(), organizationId: v.optional(v.id("organizations")), type: principalType, name: v.string(), personId: v.optional(v.id("people")), externalSubject: v.optional(v.string()), status: v.union(v.literal("active"), v.literal("disabled")), createdAt: v.number(), updatedAt: v.number() }).index("by_public_id", ["publicId"]).index("by_organization", ["organizationId"]).index("by_external_subject", ["externalSubject"]),
  apiKeys: defineTable({ principalId: v.id("principals"), organizationId: v.optional(v.id("organizations")), prefix: v.string(), secretHash: v.string(), scopes: v.array(v.string()), expiresAt: v.optional(v.number()), revokedAt: v.optional(v.number()), lastUsedAt: v.optional(v.number()), createdAt: v.number() }).index("by_hash", ["secretHash"]).index("by_principal", ["principalId"]),
  promptVersions: defineTable({ organizationId: v.id("organizations"), layer: v.union(v.literal("base"), v.literal("organization")), version: v.number(), content: v.string(), status: v.union(v.literal("draft"), v.literal("published"), v.literal("archived")), publishedAt: v.optional(v.number()), createdBy: v.id("principals"), createdAt: v.number() }).index("by_organization_layer_status", ["organizationId", "layer", "status"]),
  toolManifests: defineTable({ organizationId: v.id("organizations"), version: v.number(), status: v.union(v.literal("draft"), v.literal("published"), v.literal("archived")), tools: v.array(v.object({ name: v.string(), description: v.string(), requiredScopes: v.array(v.string()), maxResults: v.number(), enabled: v.boolean() })), createdBy: v.id("principals"), createdAt: v.number(), publishedAt: v.optional(v.number()) }).index("by_organization_status", ["organizationId", "status"]),
  notificationPolicies: defineTable({ organizationId: v.id("organizations"), serviceId: v.optional(v.id("services")), messageStartMinute: v.number(), messageEndMinute: v.number(), callStartMinute: v.number(), callEndMinute: v.number(), attempts: v.array(v.object({ offsetMinutes: v.number(), channel, purpose: v.union(v.literal("confirmation"), v.literal("reminder")) })), autoReleaseAtMinutes: v.number(), alternateChannelRequired: v.boolean(), createdAt: v.number(), updatedAt: v.number() }).index("by_organization_service", ["organizationId", "serviceId"]),
  communicationConsents: defineTable({ organizationId: v.id("organizations"), personId: v.id("people"), channel, purpose: v.union(v.literal("transactional"), v.literal("confirmation"), v.literal("marketing")), status: v.union(v.literal("granted"), v.literal("denied"), v.literal("opted_out")), source: v.string(), recordedAt: v.number(), updatedAt: v.number() }).index("by_person_channel_purpose", ["personId", "channel", "purpose"]),
  notificationDeliveries: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), bookingId: v.optional(v.id("bookings")), personId: v.id("people"), channel, purpose: v.string(), provider: v.string(), scheduledFor: v.number(), status: v.union(v.literal("queued"), v.literal("dispatched"), v.literal("delivered"), v.literal("failed"), v.literal("responded")), externalId: v.optional(v.string()), attempt: v.number(), deliveredAt: v.optional(v.number()), resultCode: v.optional(v.string()), createdAt: v.number(), updatedAt: v.number() }).index("by_booking", ["bookingId"]).index("by_status_schedule", ["status", "scheduledFor"]).index("by_public_id", ["publicId"]),
  outboxEvents: defineTable({ eventId: v.string(), eventType: v.string(), version: v.number(), organizationId: v.id("organizations"), aggregateType: v.string(), aggregatePublicId: v.string(), payload: structuredRecord, status: v.union(v.literal("pending"), v.literal("processing"), v.literal("delivered"), v.literal("failed")), attempts: v.number(), availableAt: v.number(), lastError: v.optional(v.string()), occurredAt: v.number(), updatedAt: v.number() }).index("by_event_id", ["eventId"]).index("by_status_available", ["status", "availableAt"]),
  webhookEndpoints: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), url: v.string(), secretEncrypted: v.string(), encryptionKeyVersion: v.number(), eventTypes: v.array(v.string()), status: v.union(v.literal("active"), v.literal("disabled")), createdAt: v.number(), updatedAt: v.number() }).index("by_organization", ["organizationId"]),
  webhookReceipts: defineTable({ provider: v.string(), externalEventId: v.string(), eventType: v.string(), organizationId: v.optional(v.id("organizations")), payloadHash: v.string(), status: v.union(v.literal("accepted"), v.literal("ignored"), v.literal("failed")), receivedAt: v.number(), processedAt: v.optional(v.number()), errorCode: v.optional(v.string()) }).index("by_provider_event", ["provider", "externalEventId"]),
  integrationProvisioning: defineTable({ organizationId: v.id("organizations"), provider: v.union(v.literal("chatwoot"), v.literal("evolution"), v.literal("n8n"), v.literal("meta_cloud")), step: v.string(), idempotencyKey: v.string(), externalAccountId: v.optional(v.string()), externalResourceId: v.optional(v.string()), encryptedCredential: v.optional(v.string()), encryptionKeyVersion: v.optional(v.number()), state: v.union(v.literal("pending"), v.literal("in_progress"), v.literal("waiting_for_qr"), v.literal("connected"), v.literal("failed")), lastError: v.optional(v.string()), attempts: v.number(), createdAt: v.number(), updatedAt: v.number() }).index("by_organization_provider", ["organizationId", "provider"]).index("by_provider_external", ["provider", "externalResourceId"]).index("by_idempotency", ["idempotencyKey"]),
  onboardingSessions: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), ownerPersonId: v.id("people"), ownerPhoneE164: v.string(), ownerEmail: v.string(), phoneAllowed: v.boolean(), webhookVerified: v.boolean(), emailOtpHash: v.optional(v.string()), emailOtpExpiresAt: v.optional(v.number()), emailVerifiedAt: v.optional(v.number()), state: v.string(), completedSteps: v.array(v.string()), explicitPublishConsentAt: v.optional(v.number()), createdAt: v.number(), updatedAt: v.number() }).index("by_public_id", ["publicId"]).index("by_organization", ["organizationId"]),
  auditEvents: defineTable({ publicId: v.string(), organizationId: v.id("organizations"), actor: auditActor, action: v.string(), targetType: v.string(), targetPublicId: v.string(), ipHash: v.optional(v.string()), data: structuredRecord, occurredAt: v.number() }).index("by_organization_time", ["organizationId", "occurredAt"]).index("by_target", ["targetType", "targetPublicId"]),
})
