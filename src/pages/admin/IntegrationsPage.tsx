import { PageContainer } from "@/components/layout/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function IntegrationsPage() {
  return (
    <PageContainer>
      <h1 className="mb-4 text-xl font-semibold">Integrations</h1>
      <Card>
        <CardHeader>
          <CardTitle>Providers</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Internal provider is the MVP default. n8n webhook configuration will live here next.
        </CardContent>
      </Card>
    </PageContainer>
  )
}
