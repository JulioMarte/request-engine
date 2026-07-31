import { v } from "convex/values"

export const organizationStatus = v.union(v.literal("draft"), v.literal("published"), v.literal("suspended"))
export const membershipRole = v.union(
  v.literal("owner"),
  v.literal("admin"),
  v.literal("receptionist"),
  v.literal("provider"),
  v.literal("insurance_billing"),
)
export const bookingMode = v.union(v.literal("fixed_time"), v.literal("arrival_window"), v.literal("class_session"))
export const modality = v.union(
  v.literal("onsite"),
  v.literal("virtual"),
  v.literal("at_customer_location"),
  v.literal("hybrid"),
)
export const price = v.object({
  amountMinor: v.number(),
  currency: v.string(),
  type: v.union(v.literal("fixed"), v.literal("from"), v.literal("free"), v.literal("quote")),
})
export const bookingStatus = v.union(
  v.literal("pending_confirmation"),
  v.literal("confirmed"),
  v.literal("checked_in"),
  v.literal("in_service"),
  v.literal("completed"),
  v.literal("rescheduled"),
  v.literal("cancelled_unconfirmed"),
  v.literal("cancelled_by_patient"),
  v.literal("cancelled_by_business"),
  v.literal("no_show"),
)
export const principalType = v.union(
  v.literal("platform"),
  v.literal("organization"),
  v.literal("agent"),
  v.literal("integration"),
  v.literal("human"),
)
export const channel = v.union(v.literal("whatsapp"), v.literal("sms"), v.literal("email"), v.literal("voice"))
export const shift = v.union(v.literal("morning"), v.literal("afternoon"), v.literal("evening"))
export const actor = v.object({
  principalId: v.optional(v.id("principals")),
  type: principalType,
  label: v.optional(v.string()),
})
export const structuredValue = v.union(v.string(), v.number(), v.boolean(), v.null())
export const structuredRecord = v.record(v.string(), structuredValue)
export const requiredField = v.union(
  v.literal("full_name"),
  v.literal("email"),
  v.literal("phone"),
  v.literal("identity_document"),
  v.literal("guardian"),
  v.literal("insurance_coverage"),
)

