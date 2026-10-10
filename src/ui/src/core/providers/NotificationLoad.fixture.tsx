import "@/i18n";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { AuthProvider, useAuth } from "./AuthProvider";
import HeaderUserNotification from "@/components/Header/HeaderUserNotification";
import Tooltip from "@/components/base/Tooltip";
import useAuthStore from "@/core/stores/AuthStore";
import { api } from "@/core/helpers/Api";
useAuthStore.setState({ pageLoaded: true });
let notificationReads = 0;
const base = { created_at: new Date(), updated_at: new Date() };
const user = {
    ...base,
    uid: "fixture-owner",
    type: "user",
    email: "owner@example.invalid",
    firstname: "Owner",
    lastname: "Test",
    username: "owner",
    is_admin: false,
    user_groups: [],
    subemails: [],
    api_key_role_actions: [],
    setting_role_actions: [],
    mcp_role_actions: [],
};
api.defaults.adapter = async (config) => {
    let data: unknown = {};
    if (config.url?.endsWith("/auth/refresh")) data = { access_token: "synthetic-token" };
    if (config.url?.endsWith("/auth/me")) data = { user, bots: [] };
    if (config.url?.endsWith("/notifications")) {
        notificationReads++;
        data = { notifications: [], has_more: false, unread_count: 0 };
        document.getElementById("reads")!.textContent = String(notificationReads);
    }
    return { config, data, status: 200, statusText: "OK", headers: {} };
};
function Fixture() {
    const { currentUser } = useAuth();
    return (
        <>
            <output id="reads">0</output>
            <output id="state">{currentUser ? "loaded" : "loading"}</output>
            {currentUser && <HeaderUserNotification currentUser={currentUser} />}
        </>
    );
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
            <Tooltip.Provider>
                <AuthProvider>
                    <Fixture />
                </AuthProvider>
            </Tooltip.Provider>
        </MemoryRouter>
    </QueryClientProvider>
);
