import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";
import BoardSettingsApps from "./BoardSettingsApps";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
import { api } from "@/core/helpers/Api";
const writes: unknown[] = [];
const missing = new URLSearchParams(location.search).has("missing");
let repaired = false;
let disabled = false;
Object.assign(window, { workflowWrites: writes });
api.defaults.adapter = async (config) => {
    if (config.url?.endsWith("/connections")) return { config, status: 200, statusText: "OK", headers: {}, data: { items: [], next_cursor: null } };
    if (config.method === "put" || config.method === "post") {
        writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
        if (!config.url?.endsWith("/workflow")) repaired = true;
        if (config.url?.endsWith("/disable")) disabled = true;
    }
    if (config.url?.endsWith("/settings/apps"))
        return {
            config,
            status: 200,
            statusText: "OK",
            headers: {},
            data: {
                apps: ["github", "glitchtip", "dokploy"].map((key) => ({
                    key,
                    name: { github: "GitHub", glitchtip: "GlitchTip", dokploy: "Dokploy" }[key],
                    binding:
                        key === "github"
                            ? {
                                  uid: "binding",
                                  revision: "a".repeat(64),
                                  state: !disabled && new URLSearchParams(location.search).has("enabled") ? "enabled" : "disabled",
                                  granted_capabilities: [],
                                  stage_transitions_enabled: false,
                              }
                            : null,
                    resources: {
                        selected_count: key === "github" ? (new URLSearchParams(location.search).has("large") ? 2468 : 2) : 0,
                        access_counts: key === "github" ? { granted: new URLSearchParams(location.search).has("large") ? 1234 : 1, denied: 1 } : {},
                        health_counts: key === "github" ? { healthy: 1, degraded: 1 } : {},
                        connection_counts: key === "github" ? { connected: 2 } : {},
                    },
                    workflow_requirements: key === "dokploy" ? null : { required: ["active", "review", "closed"], optional: [] },
                })),
            },
        };
    return {
        config,
        status: 200,
        statusText: "OK",
        headers: {},
        data: {
            binding: { uid: "binding", revision: "a".repeat(64), workflow_mapping: { active: "one" } },
            column_names: { one: "Doing", two: "Implementation" },
            available_columns: [
                { uid: "two", name: "Implementation", workflow_stage: new URLSearchParams(location.search).has("replace") ? "review" : null },
            ],
            choices: [
                {
                    stage: "active",
                    required: true,
                    status: missing && !repaired ? "missing" : "resolved",
                    column_uid: missing && !repaired ? null : "one",
                    candidates: missing && !repaired ? [] : ["one", "two"],
                },
            ],
        },
    };
};
const base = { created_at: new Date(), updated_at: new Date() };
const readonly = new URLSearchParams(location.search).has("readonly");
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
await i18n.changeLanguage(new URLSearchParams(location.search).get("lang") ?? "en-US");
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <BoardSettingsProvider project={project} currentUser={user}>
            <main className="mx-auto max-w-2xl p-4">
                {new URLSearchParams(location.search).has("store") ? <BoardSettingsApps /> : <BoardSettingsAppWorkflow />}
            </main>
        </BoardSettingsProvider>
    </QueryClientProvider>
);
