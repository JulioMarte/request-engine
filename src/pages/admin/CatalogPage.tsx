import { PageContainer } from "@/components/layout/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function CatalogPage() {
  return (
    <PageContainer>
      <h1 className="mb-4 text-xl font-semibold">Catalog</h1>
      <Card>
        <CardHeader>
          <CardTitle>Catalog Item</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Input placeholder="Name" />
          <Input placeholder="Fulfillment type" />
          <Button>Add</Button>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
