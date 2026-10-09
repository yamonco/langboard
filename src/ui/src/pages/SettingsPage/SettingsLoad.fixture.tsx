import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router";
import WorkbenchRouteLayout from "@/components/Layout/WorkbenchRouteLayout";
import DashboardStyledLayout from "@/components/Layout/DashboardStyledLayout";
import useGetSettingRoles from "@/controllers/api/settings/useGetSettingRoles";
import SettingsLoadState from "./SettingsLoadState";
import "@/i18n";
import "@/assets/styles/main.css";
function Fixture() {
    const { data, error, isFetching, refetch } = useGetSettingRoles({ interceptToast: true });
    return (
        <DashboardStyledLayout
            headerNavs={[]}
            headerTitle="Settings"
            activityRailItems={data ? [{ icon: "key-round", label: "API keys", active: true, onClick: () => {} }] : []}
            aria-busy={isFetching}
        >
            {data ? <p>Settings ready</p> : <SettingsLoadState error={Boolean(error)} isFetching={isFetching} retry={() => void refetch()} />}
        </DashboardStyledLayout>
    );
}
const router = createMemoryRouter([{ element: <WorkbenchRouteLayout />, children: [{ path: "/", element: <Fixture /> }] }]);
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <RouterProvider router={router} />
    </QueryClientProvider>
);
