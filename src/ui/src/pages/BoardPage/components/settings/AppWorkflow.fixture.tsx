import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";
import BoardSettingsApps from "./BoardSettingsApps";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
import { AxiosError } from "axios";
import { api } from "@/core/helpers/Api";
const writes: unknown[] = [];
let inbound = [{ connection_uid: "connection1", ownership: "personal", state: "connected", revision: "a".repeat(64) }];
let inboundFailed = false;
let consentFailed = false;
let resourceRows: { resource_uid: string; resource_type: string; external_resource_id: string; selected: boolean; access_revision: number }[] = [];
let credentialRows: { credential_uid: string; expires_at: string; revoked_at: string | null }[] = [];
const inboundReads: string[] = [];
Object.assign(window, { inboundReads });
const missing = new URLSearchParams(location.search).has("missing");
let repaired = false;
let disabled = false;
Object.assign(window, { workflowWrites: writes });
api.defaults.adapter = async (config) => {
    if (config.url?.includes("/credentials")) {
        if (config.method === "post") {
            writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
            if (config.url.endsWith("/revoke")) credentialRows = credentialRows.map(row => ({ ...row, revoked_at: "2026-10-11T06:00:00Z" }));
            else {
                credentialRows = [{ credential_uid: "credential1", expires_at: "2026-10-11T07:00:00Z", revoked_at: null }];
                if (new URLSearchParams(location.search).has("credentialfail")) throw new AxiosError("Issuance response lost", "ERR_BAD_REQUEST", config, undefined, { config, status: 422, statusText: "Error", headers: {}, data: {} });
                return { config, status: 200, statusText: "OK", headers: {}, data: { token: "synthetic-once-value" } };
            }
        }
        return { config, status: 200, statusText: "OK", headers: {}, data: { items: credentialRows, next_cursor: null } };
    }
    if (config.url?.includes("/inbound-connections/") && config.url.endsWith("/resources")) {
        if (config.method === "put") {
            const body = JSON.parse(config.data ?? "{}");
            writes.push({ ...body, url: config.url });
            if (new URLSearchParams(location.search).has("resourcefail")) throw new Error("Resource result unknown");
            resourceRows = [{ resource_uid: "resource1", resource_type: body.resource_type,
                external_resource_id: body.external_resource_id, selected: body.selected, access_revision: body.selected ? 1 : 2 }];
        }
        return { config, status: 200, statusText: "OK", headers: {}, data: {
            app_revision: "a".repeat(64), binding_uid: "binding", binding_revision: "b".repeat(64),
            resource_types: ["project"], items: resourceRows, next_cursor: null,
        } };
    }
    if (config.url?.endsWith("/inbound-connections")) {
        if (config.method === "post") {
            writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
            inbound = [...inbound, { connection_uid: "connection2", ownership: "personal", state: "connected", revision: "b".repeat(64) }];
        } else inboundReads.push(config.url);
        return { config, status: 200, statusText: "OK", headers: {}, data: { items: inbound, next_cursor: null } };
    }
    if (config.url?.includes("/inbound-connections/") && config.url.endsWith("/disconnect")) {
        writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
        if (new URLSearchParams(location.search).has("connectionfail") && !inboundFailed) {
            inboundFailed = true;
            throw new Error("outcome unknown");
        }
        inbound = inbound.map((item) => ({ ...item, state: "disconnected", revision: "c".repeat(64) }));
        return { config, status: 200, statusText: "OK", headers: {}, data: {} };
    }
    if (config.url?.endsWith("/governance/organizations"))
        return { config, status: 200, statusText: "OK", headers: {}, data: { items: [], next_cursor: null } };
    if (config.url?.endsWith("/connections")) return { config, status: 200, statusText: "OK", headers: {}, data: { items: [], next_cursor: null } };
    if (config.url?.endsWith("/consent") && new URLSearchParams(location.search).has("consentfail") && !consentFailed) {
        consentFailed = true;
        writes.push({ ...JSON.parse(config.data ?? "{}"), url: config.url });
        throw new Error("outcome unknown");
    }
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
                apps: ["github", "glitchtip", "dokploy", ...(new URLSearchParams(location.search).has("external") ? ["example-erp"] : [])].map(
                    (key) => ({
                        key,
                        app_revision: key === "example-erp" ? "a".repeat(64) : null,
                        inbound_connection_management: key === "example-erp",
                        name: { github: "GitHub", glitchtip: "GlitchTip", dokploy: "Dokploy" }[key] ?? "Example ERP",
                        description: "Independent issue tracker",
                        capabilities: ["panels.render"],
                        is_available: !(key === "example-erp" && new URLSearchParams(location.search).has("consentdisabled")),
                        panel:
                            key === "example-erp" && new URLSearchParams(location.search).has("panel")
                                ? { name: "ERP", url: "https://example.invalid" }
                                : null,
                        binding:
                            key === "github" || (key === "example-erp" && new URLSearchParams(location.search).has("consent"))
                                ? {
                                      uid: "binding",
                                      revision: "a".repeat(64),
                                      state: !disabled && new URLSearchParams(location.search).has("enabled") ? "enabled" : "disabled",
                                      granted_capabilities:
                                          key === "example-erp" && new URLSearchParams(location.search).has("consentdisabled")
                                              ? ["panels.render"]
                                              : [],
                                      stage_transitions_enabled: false,
                                  }
                                : null,
                        resources: {
                            selected_count: key === "github" ? (new URLSearchParams(location.search).has("large") ? 2468 : 2) : 0,
                            access_counts:
                                key === "github" ? { granted: new URLSearchParams(location.search).has("large") ? 1234 : 1, denied: 1 } : {},
                            health_counts: key === "github" ? { healthy: 1, degraded: 1 } : {},
                            connection_counts: key === "github" ? { connected: 2 } : {},
                        },
                        workflow_requirements: key === "dokploy" ? null : { required: ["active", "review", "closed"], optional: [] },
                    })
                ),
            },
        };
    return {
        config,
        status: 200,
        statusText: "OK",
        headers: {},
        data: {
            workflow_stages: {
                active: {
                    name: "In progress",
                    description: "Work underway",
                    translations: { ko: { name: "진행 중", description: "실행 중인 업무" } },
                },
                review: { name: "Review", description: "", translations: {} },
            },
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
                {new URLSearchParams(location.search).has("store") ? <BoardSettingsApps /> : <BoardSettingsAppWorkflow appKey="github" />}
            </main>
        </BoardSettingsProvider>
    </QueryClientProvider>
);
