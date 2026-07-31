import { ConvexError } from "convex/values"

export type ErrorCode =
  | "AUTHENTICATION_REQUIRED"
  | "INSUFFICIENT_SCOPE"
  | "TENANT_SCOPE_VIOLATION"
  | "NOT_FOUND"
  | "INVALID_INPUT"
  | "MISSING_REQUIRED_FIELDS"
  | "SLOT_UNAVAILABLE"
  | "CAPACITY_EXCEEDED"
  | "OFFER_EXPIRED"
  | "OFFER_ALREADY_CONSUMED"
  | "IDEMPOTENCY_CONFLICT"
  | "CONFIRMATION_EXPIRED"
  | "INVALID_STATE_TRANSITION"

export function fail(code: ErrorCode, message: string, details: Record<string, string | number | boolean | null> = {}): never {
  throw new ConvexError({ code, message, details })
}

