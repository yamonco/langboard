import { createRoot } from "react-dom/client";
import { useState } from "react";
import { AuthUser, Project } from "@/core/models";
import { BoardSettingsProvider } from "@/core/providers/BoardSettingsProvider";
import BoardSettingsGlitchTip from "./BoardSettingsGlitchTip";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const calls: unknown[] = [];
const params = new URLSearchParams(location.search);
let selected = params.has("selected");
let enabled = params.has("enabled");
const readBinding = () => ({
    uid: "binding",
    revision: "b".repeat(64),
    state: enabled ? "enabled" : "disabled",
    granted_capabilities: enabled ? (params.has("missingcap") ? ["resources.read"] : ["resources.read", "signals.read"]) : [],
});
let revision = 0;
const connection = { connection_uid: "conn", instance_url: "https://errors.example.invalid", revision: "a".repeat(64) };
Object.assign(window, { glitchtipCalls: calls });
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ method: config.method, url: config.url, data, params: config.params });
    if (params.has("delayed") && config.url?.endsWith("/resources")) await new Promise((resolve) => setTimeout(resolve, 400));
    if (params.has("deny") && config.url?.endsWith("/resources")) throw new Error("Denied");
    let result: unknown = {};
    if (config.url?.endsWith("/secret-input")) result = { input_uid: "s".repeat(43), input_url: location.origin + "/secret-input/" + "s".repeat(43) };
    else if (config.url?.includes("/secret-input/")) result = { state: "completed", secret_ref: "secret://ref/abcdefghijk" };
    else if (config.url?.endsWith("/connections"))
        result = config.method === "post" ? connection : { items: params.has("new") ? [] : [connection], next_cursor: null };
    else if (config.url?.endsWith("/resources"))
        result = {
            items: config.params?.organization
                ? config.params.cursor
                    ? [{ id: "3", slug: "second-project", name: "Second project" }]
                    : [{ id: "2", slug: "project", name: "Long project name for customer production errors" }]
                : [{ id: "1", slug: "organization", name: "Customer organization" }],
            next_cursor: config.params?.organization && params.has("pages") && !config.params.cursor ? "next" : null,
        };
    else if (config.url?.endsWith("/read-access")) {
        if (params.has("denyconsent")) throw new Error("Consent denied");
        if (params.has("delayedconsent")) await new Promise((resolve) => setTimeout(resolve, 400));
        enabled = true;
        result = readBinding();
    } else if (config.url?.endsWith("/issues/refresh")) {
        if (params.has("delayedissues")) await new Promise((resolve) => setTimeout(resolve, 400));
        if (params.has("denyissues")) throw new Error("Read denied");
        const outcomes = data.cursor ? ["unresolved", "ignored"] : ["resolved", "unresolved", "ignored"];
        result = {
            resource_uid: params.has("wrongresource") ? "other" : "resource",
            accepted_count: params.has("empty") ? 0 : outcomes.length,
            limit: 25,
            semantics: "status_observation",
            next_cursor: params.has("issuepages") && !data.cursor ? "issue-next" : null,
            items: params.has("empty")
                ? []
                : outcomes.map((outcome, index) => ({
                      event_type: "issue.status_observed",
                      outcome,
                      external_id: String(data.cursor && index === 0 ? 101 : 101 + index),
                      occurred_at: data.cursor ? "2026-10-08T10:01:00Z" : "2026-10-08T10:00:00Z",
                      title: "PRIVATE TITLE",
                      stacktrace: "PRIVATE STACK",
                      raw: "PRIVATE PAYLOAD",
                  })),
        };
    } else if (config.url?.endsWith("/remove")) {
        selected = false;
        result = { access_revision: ++revision };
    } else if (config.url?.endsWith("/projects")) {
        if (config.method === "post") {
            selected = true;
            revision++;
        }
        const item = {
            resource_uid: "resource",
            project_id: "2",
            access_revision: revision,
            access_state: params.has("revoked") ? "revoked" : "granted",
            selected,
            path: [
                { type: "organization", id: "organization" },
                { type: "project", id: "2", slug: "project" },
            ],
        };
        result =
            config.method === "post"
                ? item
                : { binding: params.has("nobinding") ? null : readBinding(), items: revision || selected ? [item] : [], next_cursor: null };
    }
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
const base = { created_at: new Date(), updated_at: new Date() };
const readonly = params.has("readonly");
const user = AuthUser.Model.fromOne({ ...base, uid: "me", type: "user", firstname: "Test", lastname: "User", username: "test", is_admin: false });
function Fixture() {
    const [uid, setUID] = useState("fixture");
    const [restricted, setRestricted] = useState(readonly);
    const project = Project.Model.fromOne({
        ...base,
        uid,
        title: "Fixture",
        current_auth_role_actions: restricted ? ["read"] : ["*"],
        all_members: [],
        labels: [],
        invited_member_uids: [],
    });
    return (
        <>
            <button onClick={() => setUID("other")}>Switch board</button>
            <button onClick={() => setRestricted(true)}>Remove permission</button>
            <BoardSettingsProvider project={project} currentUser={user}>
                <main className="mx-auto max-w-xl p-4">
                    <BoardSettingsGlitchTip />
                </main>
            </BoardSettingsProvider>
        </>
    );
}
await i18n.changeLanguage(params.get("language") || "en-US");
createRoot(document.getElementById("root")!).render(<Fixture />);
