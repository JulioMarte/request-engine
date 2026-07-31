import { useMemo, useState } from "react"
import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"
import type { AiMode } from "@/features/ai-control/lib/ai-mode"

export function useAiState(context: ChatwootDashboardContext | null) {
  const [localMode, setLocalMode] = useState<AiMode>("auto")

  const state = useMemo(
    () => ({
      mode: localMode,
      lastEvent: context?.conversationId ? "Contexto cargado" : "Esperando contexto de Chatwoot",
      summary: context?.conversationId
        ? `La conversacion ${context.conversationId} esta lista para control de IA.`
        : "Abre esta app dentro de Chatwoot o envia un payload postMessage de contexto.",
    }),
    [context?.conversationId, localMode],
  )

  return {
    state,
    setMode: setLocalMode,
    isBackendConnected: false,
  }
}
