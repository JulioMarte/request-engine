import { createBrowserRouter, Navigate } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { AdminHomePage } from "@/pages/admin/AdminHomePage"
import { CatalogPage } from "@/pages/admin/CatalogPage"
import { IntegrationsPage } from "@/pages/admin/IntegrationsPage"
import { KnowledgePage } from "@/pages/admin/KnowledgePage"
import { TenantsPage } from "@/pages/admin/TenantsPage"
import { ChatwootDashboardPage } from "@/pages/dashboard-app/ChatwootDashboardPage"
import { NotFoundPage } from "@/pages/not-found/NotFoundPage"
import { AgentRuntimePage } from "@/pages/operations/AgentRuntimePage"
import { BookingsPage } from "@/pages/operations/BookingsPage"
import { OperationsDashboardPage } from "@/pages/operations/OperationsDashboardPage"
import { QueuePage } from "@/pages/operations/QueuePage"

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/operations" replace /> },
      { path: "operations", element: <OperationsDashboardPage /> },
      { path: "operations/bookings", element: <BookingsPage /> },
      { path: "operations/queue", element: <QueuePage /> },
      { path: "operations/agents", element: <AgentRuntimePage /> },
      { path: "dashboard-app", element: <ChatwootDashboardPage /> },
      { path: "admin", element: <AdminHomePage /> },
      { path: "admin/tenants", element: <TenantsPage /> },
      { path: "admin/catalog", element: <CatalogPage /> },
      { path: "admin/knowledge", element: <KnowledgePage /> },
      { path: "admin/integrations", element: <IntegrationsPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
])
