import { createRoot } from "react-dom/client";
import { useState } from "react";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsDokploy from "./BoardSettingsDokploy";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const calls: unknown[] = [];
const params = new URLSearchParams(location.search);
const resources = new Map<
    string,
    { resource_uid: string; external_id: string; type: string; access_revision: number; selected: boolean; path: { type: string; id: string }[] }
>();
let enabled = false;
if (params.has("saved"))
    resources.set("app-1", {
        resource_uid: "resource",
        external_id: "app-1",
        type: "application",
        access_revision: 1,
        selected: true,
        path: [{ type: "application", id: "app-1" }],
    });
const readAccess = () => ({
    uid: "board-binding",
    revision: "b".repeat(64),
    state: enabled ? "enabled" : "configured",
    granted_capabilities: enabled ? ["resources.read", "signals.read", "deployments.read"] : [],
});
let revision = 0;
const connection = { connection_uid: "conn", instance_url: "https://deploy.example.invalid", revision: "a".repeat(64) };
let webhookRevision = params.has("webhook-enabled") ? 7 : 0;
let webhookState = params.has("webhook-enabled") ? "enabled" : "unconfigured";
let notificationID: string | null = params.has("webhook-enabled") ? "notification-1" : null;
const webhookHealth = () => ({
    can_configure: !params.has("revoked"),
    config_revision: webhookRevision,
    state: webhookState,
    receiver_path: webhookRevision ? "/apps/dokploy/notifications/config" : null,
    notification_id: notificationID,
    provider_config: "unknown",
    last_received_at: params.has("receipt") && (resources.size || webhookRevision) ? "2026-10-08T01:02:03Z" : null,
    local_evidence: "authenticated_notification_receipt",
    connection_state: params.has("revoked") ? "revoked" : "connected",
    connection_revision: "c".repeat(64),
    binding_revision: resources.size || webhookRevision ? "d".repeat(64) : null,
    resources: params.has("revoked")
        ? []
        : [...resources.values()].filter((row) => row.selected).map((row) => ({ resource_uid: row.resource_uid, health: "healthy" })),
});
Object.assign(window, { dokployCalls: calls });
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ method: config.method, url: config.url, data, params: config.params });
    if (params.has("denyhealth") && config.url?.endsWith("/webhook-health")) throw new Error("Denied");
    if (params.has("delayed") && (config.url?.endsWith("/resources") || config.url?.endsWith("/refresh") || config.url?.endsWith("/enable-read")))
        await new Promise((resolve) => setTimeout(resolve, 400));
    if (params.has("deny") && config.url?.endsWith("/resources")) throw new Error("Denied");
    if (params.has("delayed-health") && config.url?.endsWith("/webhook-health")) await new Promise((resolve) => setTimeout(resolve, 400));
    if (params.has("delayed-webhook-post") && config.method === "post" && config.url?.includes("/webhook-"))
        await new Promise((resolve) => setTimeout(resolve, 400));
    let result: unknown = {};
    if (config.url?.endsWith("/webhook-verify")) {
        if (params.has("delayed-verify")) await new Promise((resolve) => setTimeout(resolve, 400));
        const outcome = params.has("mismatch") ? "mismatch" : params.has("unavailable") ? "unavailable" : "matched";
        result = {
            provider_config: outcome,
            checked_at: "2026-10-08T01:02:03Z",
            config_revision: webhookRevision,
            connection_revision: "c".repeat(64),
            binding_revision: "d".repeat(64),
            checks:
                outcome === "unavailable"
                    ? null
                    : {
                          notification_id: true,
                          custom_type: true,
                          endpoint: outcome !== "mismatch",
                          authorization: true,
                          build_success: true,
                          build_error: true,
                      },
        };
        if (params.has("invalid-verify")) result = { ...(result as object), checks: { endpoint: "raw-secret-provider-value" } };
        if (params.has("stale-verify")) result = { ...(result as object), config_revision: webhookRevision - 1 };
    } else if (config.url?.endsWith("/webhook-health")) result = webhookHealth();
    else if (config.url?.endsWith("/webhook-config") || config.url?.endsWith("/webhook-disable")) {
        if (
            data.expected_revision !== "c".repeat(64) ||
            data.expected_binding_revision !== "d".repeat(64) ||
            data.expected_config_revision !== webhookRevision
        )
            throw new Error("Invalid webhook revisions");
        if (config.url.endsWith("/webhook-config")) notificationID = data.notification_id;
        webhookRevision++;
        webhookState = config.url.endsWith("/webhook-config") ? "enabled" : "disabled";
        result = webhookHealth();
    } else if (config.url?.endsWith("/webhook-secret-input"))
        result = { input_uid: "w".repeat(43), input_url: location.origin + "/secret-input/" + "w".repeat(43) };
    else if (config.url?.endsWith("/secret-input"))
        result = { input_uid: "s".repeat(43), input_url: location.origin + "/secret-input/" + "s".repeat(43) };
    else if (config.url?.includes("/secret-input/")) result = { state: "completed", secret_ref: "secret://ref/abcdefghijk" };
    else if (config.url?.endsWith("/connections"))
        result = config.method === "post" ? connection : { items: params.has("new") ? [] : [connection], next_cursor: null };
    else if (config.url?.endsWith("/resources"))
        result = {
            items: config.params?.environment_id
                ? [
                      { id: "app-1", type: "application", name: "Customer API" },
                      { id: "compose-1", type: "compose", name: "Customer stack" },
                  ]
                : config.params?.external_project_id
                  ? [{ id: "env-1", type: "environment", name: "Production" }]
                  : [{ id: "project-1", type: "project", name: "Customer project" }],
            next_cursor: null,
        };
    else if (config.url?.endsWith("/enable-read")) {
        if (data.expected_revision !== connection.revision || data.expected_binding_revision !== readAccess().revision || !resources.size)
            throw new Error("Invalid consent request");
        enabled = true;
        result = readAccess();
    } else if (config.url?.endsWith("/refresh")) {
        const resource = [...resources.values()].find((row) => config.url?.includes(`/selected/${row.resource_uid}/`));
        if (
            !enabled ||
            !resource?.selected ||
            data.expected_revision !== connection.revision ||
            data.expected_access_revision !== resource.access_revision
        )
            throw new Error("Invalid refresh request");
        result = {
            resource_uid: resource.resource_uid,
            inserted: 1,
            items: [
                {
                    event_type: "deployment.succeeded",
                    outcome: "success",
                    occurred_at: "2026-10-08T01:02:03.000000+00:00",
                    external_id: "deployment-1",
                    logs: "sensitive-provider-log",
                    title: "sensitive-provider-title",
                },
            ],
            limit: 25,
            truncated: true,
        };
    } else if (config.url?.endsWith("/remove")) {
        const resource = [...resources.values()].find((row) => config.url?.includes(`/selected/${row.resource_uid}/`))!;
        resource.selected = false;
        resource.access_revision = ++revision;
        result = { access_revision: revision };
    } else if (config.url?.endsWith("/selected")) {
        if (config.method === "post") {
            const item = {
                resource_uid: data.external_id === "app-1" ? "resource" : "compose-resource",
                external_id: data.external_id,
                type: data.resource_type,
                access_state: "granted",
                access_revision: ++revision,
                selected: true,
                path: [
                    { type: "project", id: data.external_project_id },
                    { type: "environment", id: data.environment_id },
                    { type: data.resource_type, id: data.external_id, name: data.external_id === "app-1" ? "Customer API" : "Customer stack" },
                ],
            };
            resources.set(item.external_id, item);
            result = item;
        } else result = { items: [...resources.values()], next_cursor: null, binding: resources.size ? readAccess() : null };
    }
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
const base = { created_at: new Date(), updated_at: new Date() };
const readonly = params.has("readonly");
const user = AuthUser.Model.fromOne({ ...base, uid: "me", type: "user", firstname: "Test", lastname: "User", username: "test", is_admin: !readonly });
function Fixture() {
    const [uid, setUID] = useState("fixture");
    const [permission, setPermission] = useState(!readonly);
    const project = Project.Model.fromOne({
        ...base,
        uid,
        title: "Fixture",
        current_auth_role_actions: permission ? ["*"] : ["read"],
        all_members: [],
        labels: [],
        invited_member_uids: [],
    });
    return (
        <>
            <button onClick={() => setUID("other")}>Switch board</button>
            <button onClick={() => setPermission(false)}>Remove permission</button>
            <BoardSettingsProvider
                project={project}
                currentUser={
                    permission
                        ? user
                        : AuthUser.Model.fromOne({
                              ...base,
                              uid: "reader",
                              type: "user",
                              firstname: "Reader",
                              lastname: "User",
                              username: "reader",
                              is_admin: false,
                          })
                }
            >
                <main className="mx-auto max-w-xl p-4">
                    <BoardSettingsDokploy />
                </main>
            </BoardSettingsProvider>
        </>
    );
}
await i18n.changeLanguage("en-US");
createRoot(document.getElementById("root")!).render(<Fixture />);
