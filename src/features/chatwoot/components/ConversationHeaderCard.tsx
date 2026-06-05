import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import type { ChatwootDashboardContext } from "@/features/chatwoot/lib/chatwoot-types"

export function ConversationHeaderCard({ context }: { context: ChatwootDashboardContext | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Conversation Context</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div>
          <p className="font-medium">{context?.contactName ?? "No contact selected"}</p>
          <p className="text-xs text-muted-foreground">{context?.contactPhone ?? "Phone unavailable"}</p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <span>Account: {context?.accountId ?? "-"}</span>
          <span>Inbox: {context?.inboxId ?? "-"}</span>
          <span>Conversation: {context?.conversationId ?? "-"}</span>
          <span>Contact: {context?.contactId ?? "-"}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">{context?.conversationStatus ?? "unknown"}</Badge>
          {(context?.labels ?? []).slice(0, 4).map((label) => (
            <Badge key={label} variant="secondary">{label}</Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
