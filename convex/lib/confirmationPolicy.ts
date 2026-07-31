export type DeliveryEvidence = { status: "queued" | "dispatched" | "delivered" | "failed" | "responded", channel: string }

export function canAutoRelease(input: {
  autoReleaseUnconfirmed: boolean
  neverAutoCancel: boolean
  warned: boolean
  alternateChannelRequired: boolean
  deliveries: DeliveryEvidence[]
}) {
  if (!input.autoReleaseUnconfirmed || input.neverAutoCancel || !input.warned) return false
  const delivered = input.deliveries.some((item) => item.status === "delivered" || item.status === "responded")
  if (!delivered) return false
  if (!input.alternateChannelRequired) return true
  return new Set(input.deliveries.filter((item) => item.status !== "queued").map((item) => item.channel)).size >= 2
}

export function intervalsOverlap(firstStart: number, firstEnd: number, secondStart: number, secondEnd: number) {
  return firstStart < secondEnd && firstEnd > secondStart
}

