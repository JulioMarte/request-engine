import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"

export function ChatwootContextDebug({ context }: { context: ChatwootDashboardContext | null }) {
  if (!import.meta.env.DEV) return null

  return (
    <details className="rounded-lg border bg-card text-card-foreground shadow-sm">
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold">Contexto tecnico</summary>
      <div className="px-4 pb-4">
        <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(context, null, 2)}
        </pre>
      </div>
    </details>
  )
}
