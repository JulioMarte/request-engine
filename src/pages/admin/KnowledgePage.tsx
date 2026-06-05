import { PageContainer } from "@/components/layout/PageContainer"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export function KnowledgePage() {
  return (
    <PageContainer>
      <h1 className="mb-4 text-xl font-semibold">Knowledge</h1>
      <Card>
        <CardHeader>
          <CardTitle>Knowledge Item</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-[1fr_2fr_auto]">
          <Input placeholder="Title" />
          <Input placeholder="Answer" />
          <Button>Add</Button>
        </CardContent>
      </Card>
    </PageContainer>
  )
}
