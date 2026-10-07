import { createRoot } from "react-dom/client";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsGitHub from "./BoardSettingsGitHub";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const calls: unknown[] = [];
let healthPage = 0;
Object.assign(window, { githubCalls: calls });
const params = new URLSearchParams(location.search);
sessionStorage.setItem(
    "github-onboarding:me:fixture",
    JSON.stringify({ connection_uid: "conn", installation_url: "https://github.com/apps/fixture/installations/new" })
);
sessionStorage.setItem("github-onboarding:me:fixture:kind", params.has("manifest") ? "manifest" : "authorization");
if (params.has("new") || params.has("existing")) sessionStorage.removeItem("github-onboarding:me:fixture");
api.defaults.adapter = async (config) => {
    calls.push({ url: config.url, method: config.method, data: config.data ? JSON.parse(config.data) : null });
    if (config.url?.endsWith("/authorization")) console.log("authorization-page:" + JSON.parse(config.data).page);
    if (config.url?.endsWith("/resources/refresh"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                revision: "a".repeat(64),
                items: [],
                next_cursor: params.has("healthpages") && healthPage++ === 0 ? "cursor" : null,
                refreshed_count: 25,
            },
        };
    if (config.url?.endsWith("/health"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                state: "pending",
                next_cursor: config.params?.after ? null : "17:7",
                items: [
                    {
                        installation_id: config.params?.after ? "18" : "17",
                        account_id: "7",
                        selected_count: 4,
                        healthy_count: 1,
                        degraded_count: 1,
                        unavailable_count: 1,
                        unverified_count: 1,
                    },
                ],
            },
        };
    if (config.url?.endsWith("/app"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: { connection_uid: "stored", installation_url: "https://github.com/apps/current-app/installations/new" },
        };
    if (config.url?.endsWith("connections"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: { items: params.has("existing") ? [{ connection_uid: "stored", app_id: "42", state: "pending" }] : [], next_cursor: null },
        };
    if (config.url?.endsWith("/authorization"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: { authorization_url: "https://github.com/login/oauth/authorize?state=fixture" },
        };
    if (config.url?.endsWith("manifest"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                registration_url: "https://github.com/settings/apps/new?state=" + "s".repeat(43),
                manifest: { name: "Langboard", callback_urls: ["https://example.test/board/fixture/settings"] },
            },
        };
    if (config.url?.endsWith("manifest/complete"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: { connection_uid: "conn", installation_url: "https://github.com/apps/fixture/installations/new" },
        };
    if (config.url?.endsWith("authorization/complete"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                installations: [{ id: 17, account: { id: 7, login: "example", type: "Organization" }, suspended: false }],
                installation_proof: "p".repeat(43),
                has_more: params.has("installpages"),
                page: 1,
                next_page: params.has("installpages") ? 2 : null,
            },
        };
    if (config.url?.includes("/repositories"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                repositories: [
                    { id: 99, name: "example/frontend", archived: false },
                    { id: 100, name: "example/backend", archived: false },
                ],
                next_page: null,
            },
        };
    return {
        config,
        status: 200,
        statusText: "OK",
        headers: {},
        data: {
            revision: "a".repeat(64),
            items: [
                { repository_id: "99", connection_uid: "conn", selected: true },
                { repository_id: "101", connection_uid: "conn", selected: true },
            ],
        },
    };
};
const base = { created_at: new Date(), updated_at: new Date() };
const readonly = params.has("readonly");
const user = AuthUser.Model.fromOne({ ...base, uid: "me", type: "user", firstname: "Test", lastname: "User", username: "test", is_admin: !readonly });
const project = Project.Model.fromOne({
    ...base,
    uid: "fixture",
    title: "Fixture",
    current_auth_role_actions: readonly ? ["read"] : ["*"],
    all_members: [],
    labels: [],
    invited_member_uids: [],
});
await i18n.changeLanguage("en-US");
createRoot(document.getElementById("root")!).render(
    <BoardSettingsProvider project={project} currentUser={user}>
        <main className="mx-auto max-w-xl p-4">
            <BoardSettingsGitHub />
        </main>
    </BoardSettingsProvider>
);
