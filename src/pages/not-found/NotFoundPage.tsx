import { PageContainer } from "@/components/layout/PageContainer"
import { Button } from "@/components/ui/button"

export function NotFoundPage() {
  return (
    <PageContainer>
      <div className="rounded-lg border bg-card p-6">
        <h1 className="text-xl font-semibold">Pagina no encontrada</h1>
        <p className="mt-1 text-sm text-muted-foreground">Esta ruta no forma parte de la superficie actual.</p>
        <Button className="mt-4" onClick={() => window.location.assign("/dashboard-app")}>
          Ir al dashboard
        </Button>
      </div>
    </PageContainer>
  )
}
