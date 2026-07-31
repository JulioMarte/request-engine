export function publicId(prefix: string, convexId: string) {
  return `${prefix}_${convexId}`
}

export function opaqueToken(prefix: string, entropy: string) {
  return `${prefix}_${entropy.replace(/[^a-zA-Z0-9]/g, "").slice(-32)}`
}

