import { useEffect, useMemo, useState } from "react"
import { isProbablyEmbedded, requestChatwootContext } from "@/features/chatwoot/lib/chatwoot-post-message"
import type { ChatwootContextState, ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"

function readNumber(value: unknown): number | undefined {
  if (typeof value === "number") return value
  if (typeof value === "string" && value.trim() !== "") return Number(value)
  return undefined
}

function normalizeContext(raw: unknown): ChatwootDashboardContext | null {
  if (!raw || typeof raw !== "object") return null

  const data = raw as Record<string, unknown>
  const payload = (data.payload && typeof data.payload === "object" ? data.payload : data) as Record<string, unknown>
  const conversation = (payload.conversation && typeof payload.conversation === "object"
    ? payload.conversation
    : {}) as Record<string, unknown>
  const contact = (payload.contact && typeof payload.contact === "object" ? payload.contact : {}) as Record<string, unknown>
  const inbox = (payload.inbox && typeof payload.inbox === "object" ? payload.inbox : {}) as Record<string, unknown>
  const account = (payload.account && typeof payload.account === "object" ? payload.account : {}) as Record<string, unknown>

  const labels = Array.isArray(conversation.labels)
    ? conversation.labels.filter((label): label is string => typeof label === "string")
    : []

  return {
    accountId: readNumber(account.id ?? payload.account_id ?? payload.accountId),
    conversationId: readNumber(conversation.id ?? payload.conversation_id ?? payload.conversationId),
    contactId: readNumber(contact.id ?? payload.contact_id ?? payload.contactId),
    inboxId: readNumber(inbox.id ?? conversation.inbox_id ?? payload.inbox_id ?? payload.inboxId),
    contactName: typeof contact.name === "string" ? contact.name : undefined,
    contactPhone: typeof contact.phone_number === "string" ? contact.phone_number : undefined,
    conversationStatus: typeof conversation.status === "string" ? conversation.status : undefined,
    labels,
    customAttributes:
      conversation.custom_attributes && typeof conversation.custom_attributes === "object"
        ? (conversation.custom_attributes as Record<string, unknown>)
        : {},
    raw,
  }
}

export function useChatwootContext(): ChatwootContextState {
  const [context, setContext] = useState<ChatwootDashboardContext | null>(null)
  const [lastMessageAt, setLastMessageAt] = useState<number>()
  const isEmbedded = useMemo(() => isProbablyEmbedded(), [])

  useEffect(() => {
    function handleMessage(event: MessageEvent) {
      const normalized = normalizeContext(event.data)
      if (!normalized) return
      setContext(normalized)
      setLastMessageAt(Date.now())
    }

    window.addEventListener("message", handleMessage)
    if (isEmbedded) {
      requestChatwootContext()
    }

    return () => window.removeEventListener("message", handleMessage)
  }, [isEmbedded])

  return {
    isEmbedded,
    isConnected: Boolean(context),
    context,
    lastMessageAt,
  }
}
