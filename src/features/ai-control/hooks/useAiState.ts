import { useMemo, useState } from "react"
import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"
import type { AiMode } from "@/features/ai-control/lib/ai-mode"

export function useAiState(context: ChatwootDashboardContext | null) {
  const [localMode, setLocalMode] = useState<AiMode>("auto")

  const state = useMemo(
    () => ({
      mode: localMode,
      lastEvent: context?.conversationId ? "Context loaded" : "Waiting for Chatwoot context",
      summary: context?.conversationId
        ? `Conversation ${context.conversationId} is ready for AI control.`
        : "Open this app inside Chatwoot or send a postMessage context payload.",
    }),
    [context?.conversationId, localMode],
  )

  return {
    state,
    setMode: setLocalMode,
    isBackendConnected: false,
  }
}
