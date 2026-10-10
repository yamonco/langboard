import { createRoot } from "react-dom/client";
import { createMemoryRouter, Link, Outlet, RouterProvider, useLocation } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DashboardStyledLayout from "@/components/Layout/DashboardStyledLayout";
import { toRoutes } from "@/core/routing/workbenchRoutes";
import settings from "./Route";
import "@/i18n";
import "@/assets/styles/main.css";
function Page() {
    const { pathname } = useLocation();
    return (
        <DashboardStyledLayout
            headerNavs={[]}
            headerTitle="Settings"
            activityRailItems={[{ icon: "key-round", label: "API keys", active: pathname === "/settings/api-keys", onClick: () => {} }]}
        >
            <h1>{pathname}</h1>
            <Link to="/settings/api-keys">Open settings</Link>
            <Link to="/settings/ollama">Open unavailable Ollama</Link>
            <Outlet />
        </DashboardStyledLayout>
    );
}
// Keep production route paths, redirect elements and shell classification.
// Replace authenticated page content so this fixture makes no API or credential calls.
const settingsRoutes = {
    ...settings,
    routes: settings.routes.map((route) => (route.path === "/settings" ? { ...route, element: <Page /> } : route)),
};
const initial = new URLSearchParams(location.search).get("initial") ?? "/dashboard";
const router = createMemoryRouter(toRoutes([{ workbench: true, routes: [{ path: "/dashboard", element: <Page /> }] }, settingsRoutes]), {
    initialEntries: [initial],
});
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
    </QueryClientProvider>
);
