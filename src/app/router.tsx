import { createBrowserRouter, Navigate } from "react-router-dom"
import { AppShell } from "@/components/layout/AppShell"
import { AdminHomePage } from "@/pages/admin/AdminHomePage"
import { CatalogPage } from "@/pages/admin/CatalogPage"
import { IntegrationsPage } from "@/pages/admin/IntegrationsPage"
import { KnowledgePage } from "@/pages/admin/KnowledgePage"
import { TenantsPage } from "@/pages/admin/TenantsPage"
import { ChatwootDashboardPage } from "@/pages/dashboard-app/ChatwootDashboardPage"
import { NotFoundPage } from "@/pages/not-found/NotFoundPage"

export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/dashboard-app" replace /> },
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
