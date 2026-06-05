import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/common/EmptyState"
import { PageContainer } from "@/components/layout/PageContainer"
import { AiModeCard } from "@/features/ai-control/components/AiModeCard"
import { useAiState } from "@/features/ai-control/hooks/useAiState"
import { ChatwootContextDebug } from "@/features/chatwoot/components/ChatwootContextDebug"
import { ConversationHeaderCard } from "@/features/chatwoot/components/ConversationHeaderCard"
import { useChatwootContext } from "@/features/chatwoot/hooks/useChatwootContext"

export function ChatwootDashboardPage() {
  const chatwoot = useChatwootContext()
  const ai = useAiState(chatwoot.context)

  return (
    <PageContainer>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Chatwoot Dashboard App</h1>
          <p className="text-sm text-muted-foreground">Contextual controls for the active conversation.</p>
        </div>
        <Badge variant={chatwoot.isConnected ? "success" : "warning"}>
          {chatwoot.isConnected ? "Connected" : chatwoot.isEmbedded ? "Waiting for context" : "Standalone"}
        </Badge>
      </div>

      {!chatwoot.isEmbedded && (
        <div className="mb-4">
          <EmptyState
            title="Not embedded in Chatwoot"
            description="The page is still usable for development, but production context arrives through Chatwoot postMessage."
          />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="space-y-4">
          <ConversationHeaderCard context={chatwoot.context} />
          <Card>
            <CardHeader>
              <CardTitle>Current Request</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
              <div>
                <p className="text-xs text-muted-foreground">Intent</p>
                <p className="font-medium">No request detected</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <p className="font-medium">new</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Next action</p>
                <p className="font-medium">Wait for incoming message</p>
              </div>
            </CardContent>
          </Card>
          <ChatwootContextDebug context={chatwoot.context} />
        </div>
        <div className="space-y-4">
          <AiModeCard
            lastEvent={ai.state.lastEvent}
            mode={ai.state.mode}
            onChange={ai.setMode}
            summary={ai.state.summary}
          />
          <Card>
            <CardHeader>
              <CardTitle>Quick Actions</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              Suggested actions will unlock when a request is active.
            </CardContent>
          </Card>
        </div>
      </div>
    </PageContainer>
  )
}
