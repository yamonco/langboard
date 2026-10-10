import "@/i18n";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { useTranslation } from "react-i18next";
import { AuthProvider, useAuth } from "./AuthProvider";
import useAuthStore, { getAuthStore } from "@/core/stores/AuthStore";
import { api } from "@/core/helpers/Api";

useAuthStore.setState({ state: "loaded", pageLoaded: true });
function Fixture() {
    const { currentUser } = useAuth();
    const [, i18n] = useTranslation();
    const login = async (uid: string, language: string) => {
        api.defaults.adapter = async (config) => ({
            status: 200,
            statusText: "OK",
            headers: {},
            config,
            data: { user: { uid, preferred_lang: language, created_at: new Date(), updated_at: new Date() }, bots: [] },
        });
        await getAuthStore().updateToken("fixture-session", api);
    };
    return (
        <>
            <output>{JSON.stringify({ user: currentUser?.uid ?? null, language: i18n.language })}</output>
            <button onClick={() => login("user-a", "ko-KR")}>Login A</button>
            <button onClick={() => login("user-b", "ja-JP")}>Login B</button>
            <button onClick={() => login("user-invalid", "zh-Hant")}>Login invalid</button>
            <button onClick={() => login("user-unset", "")}>Login unset</button>
            <button onClick={() => getAuthStore().removeToken()}>Logout</button>
            <button onClick={() => i18n.changeLanguage("zh-CN")}>Local Chinese</button>
            <button onClick={() => login("user-a", "ko-KR")}>Refresh A</button>
        </>
    );
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
            <AuthProvider>
                <Fixture />
            </AuthProvider>
        </MemoryRouter>
    </QueryClientProvider>
);
