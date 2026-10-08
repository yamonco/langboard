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
let selected = false;
let revision = 0;
const connection = { connection_uid: "conn", instance_url: "https://deploy.example.invalid", revision: "a".repeat(64) };
Object.assign(window, { dokployCalls: calls });
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
    else if (config.url?.endsWith("/remove")) {
        selected = false;
        result = { access_revision: ++revision };
    } else if (config.url?.endsWith("/selected")) {
        if (config.method === "post") {
            selected = true;
            revision++;
        }
        const item = {
            resource_uid: "resource",
            external_id: data?.external_id ?? "app-1",
            type: data?.resource_type ?? "application",
            access_revision: revision,
            selected,
            path: [
                { type: "organization", id: "organization" },
                { type: "project", id: "2", slug: "project" },
            ],
        };
        result = config.method === "post" ? item : { items: revision ? [item] : [], next_cursor: null };
    }
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
const base = { created_at: new Date(), updated_at: new Date() };
const readonly = params.has("readonly");
const user = AuthUser.Model.fromOne({ ...base, uid: "me", type: "user", firstname: "Test", lastname: "User", username: "test", is_admin: !readonly });
function Fixture() {
    const [uid, setUID] = useState("fixture");
    const project = Project.Model.fromOne({
        ...base,
        uid,
        title: "Fixture",
        current_auth_role_actions: readonly ? ["read"] : ["*"],
        all_members: [],
        labels: [],
        invited_member_uids: [],
    });
    return (
        <>
            <button onClick={() => setUID("other")}>Switch board</button>
            <BoardSettingsProvider project={project} currentUser={user}>
                <main className="mx-auto max-w-xl p-4">
                    <BoardSettingsDokploy />
                </main>
            </BoardSettingsProvider>
        </>
    );
}
await i18n.changeLanguage("en-US");
createRoot(document.getElementById("root")!).render(<Fixture />);
