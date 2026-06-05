import { PageContainer } from "@/components/layout/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { AuthStatusCard } from "@/features/auth/components/AuthStatusCard"

const sections = ["Tenants", "Channels", "Catalog", "Knowledge", "Integrations"]

export function AdminHomePage() {
  return (
    <PageContainer>
      <h1 className="mb-4 text-xl font-semibold">Admin</h1>
      <div className="mb-4">
        <AuthStatusCard />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sections.map((section) => (
          <Card key={section}>
            <CardHeader>
              <CardTitle>{section}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">Basic admin surface ready for Convex data.</CardContent>
          </Card>
        ))}
      </div>
    </PageContainer>
  )
}
