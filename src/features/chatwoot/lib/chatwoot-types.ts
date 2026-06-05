export type ChatwootConversationStatus = "open" | "resolved" | "pending" | "snoozed" | string

export type ChatwootDashboardContext = {
  accountId?: number
  conversationId?: number
  contactId?: number
  inboxId?: number
  contactName?: string
  contactPhone?: string
  conversationStatus?: ChatwootConversationStatus
  labels: string[]
  customAttributes: Record<string, unknown>
  raw?: unknown
}

export type ChatwootContextState = {
  isEmbedded: boolean
  isConnected: boolean
  context: ChatwootDashboardContext | null
  lastMessageAt?: number
}
