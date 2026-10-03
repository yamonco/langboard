import "@/assets/styles/main.css";
import "@/i18n";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { AuthUser } from "@/core/models";
import { AccountSettingProvider } from "@/core/providers/AccountSettingProvider";
import Toast from "@/components/base/Toast";
import PreferenceLanguage from "./PreferenceLanguage";
import UserAvatar from "@/components/UserAvatar";
import UserPreferenceLanguageSwitcher from "@/components/LanguageSwitcher/UserPreference";
const user = AuthUser.Model.fromOne({
    uid: "default-language-fixture",
    type: "user",
    firstname: "Language",
    lastname: "Fixture",
    username: "language-fixture",
    preferred_lang: localStorage.getItem("fixture-preferred-lang") || "en-US",
    created_at: new Date(),
    updated_at: new Date(),
});
function Fixture() {
    const preferred = user.useField("preferred_lang");
    const [, i18n] = useTranslation();
    useEffect(() => {
        localStorage.setItem("fixture-preferred-lang", preferred);
    }, [preferred]);
    return (
        <main className="mx-auto max-w-xl p-6">
            <AccountSettingProvider currentUser={user}>
                <PreferenceLanguage />
            </AccountSettingProvider>
            <UserAvatar.Root userOrBot={user}>
                <UserAvatar.List>
                    <UserAvatar.ListItem
                        onClick={() => {
                            document.title = "Account action selected";
                        }}
                    >
                        Open account action
                    </UserAvatar.ListItem>
                    <UserPreferenceLanguageSwitcher currentUser={user} variant="outline" triggerType="text" />
                </UserAvatar.List>
            </UserAvatar.Root>
            <output>{JSON.stringify({ preferred, language: i18n.language })}</output>
            <Toast.Area />
        </main>
    );
}
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <Fixture />
    </QueryClientProvider>
);
