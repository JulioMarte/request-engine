import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"

export function ChatwootContextDebug({ context }: { context: ChatwootDashboardContext | null }) {
  if (!import.meta.env.DEV) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Context Debug</CardTitle>
      </CardHeader>
      <CardContent>
        <pre className="max-h-56 overflow-auto rounded-md bg-muted p-3 text-xs">
          {JSON.stringify(context, null, 2)}
        </pre>
      </CardContent>
    </Card>
  )
}
