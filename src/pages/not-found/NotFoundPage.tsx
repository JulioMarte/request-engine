import { PageContainer } from "@/components/layout/PageContainer"
import { Button } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <PageContainer>
      <div className="rounded-lg border bg-card p-6">
        <h1 className="text-xl font-semibold">Page not found</h1>
        <p className="mt-1 text-sm text-muted-foreground">This route is not part of the MVP shell.</p>
        <Button className="mt-4" onClick={() => window.location.assign("/dashboard-app")}>
          Go to Dashboard App
        </Button>
      </div>
    </PageContainer>
  )
}
