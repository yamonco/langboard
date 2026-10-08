import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import useGetSettingRoles from "@/controllers/api/settings/useGetSettingRoles";
import SettingsLoadState from "./SettingsLoadState";
import "@/i18n";
import "@/assets/styles/main.css";
function Fixture() {
    const { data, error, isFetching, refetch } = useGetSettingRoles({ interceptToast: true });
    return data ? <p>Settings ready</p> : <SettingsLoadState error={Boolean(error)} isFetching={isFetching} retry={() => void refetch()} />;
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <Fixture />
    </QueryClientProvider>
);
