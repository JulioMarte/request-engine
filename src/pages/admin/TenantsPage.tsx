import { PageContainer } from "@/components/layout/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function TenantsPage() {
  return (
    <PageContainer>
      <h1 className="mb-4 text-xl font-semibold">Tenants</h1>
      <Card>
        <CardHeader>
          <CardTitle>Demo Tenant</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Input placeholder="Business name" />
          <Input placeholder="Chatwoot account ID" />
          <Button>Create</Button>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
