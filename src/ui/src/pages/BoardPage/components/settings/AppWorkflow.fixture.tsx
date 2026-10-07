import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
import { api } from "@/core/helpers/Api";
const writes: unknown[] = [];
const missing = new URLSearchParams(location.search).has("missing");
let repaired = false;
Object.assign(window, { workflowWrites: writes });
api.defaults.adapter = async (config) => {
    if (config.method === "put" || config.method === "post") {
        writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
        if (!config.url?.endsWith("/workflow")) repaired = true;
    }
    return {
        config,
        status: 200,
        statusText: "OK",
        headers: {},
        data: {
            binding: { uid: "binding", revision: "a".repeat(64), workflow_mapping: { active: "one" } },
            column_names: { one: "Doing", two: "Implementation" },
            available_columns: [{ uid: "two", name: "Implementation", workflow_stage: null }],
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
await i18n.changeLanguage("en-US");
createRoot(document.getElementById("root")!).render(
    <QueryClientProvider client={new QueryClient()}>
        <BoardSettingsProvider project={project} currentUser={user}>
            <main className="mx-auto max-w-2xl p-4">
                <BoardSettingsAppWorkflow />
            </main>
        </BoardSettingsProvider>
    </QueryClientProvider>
);
