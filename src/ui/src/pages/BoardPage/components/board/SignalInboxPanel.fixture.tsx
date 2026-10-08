import { createRoot } from "react-dom/client";
import { useState } from "react";
import SignalInboxPanel from "./SignalInboxPanel";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const params = new URLSearchParams(location.search);
const calls: { url?: string; method?: string; data: unknown }[] = [];
Object.assign(window, { inboxCalls: calls });
let linked = false;
const linkedDeployments = new Set<string>();
const callbacks = new Map<string, (data?: unknown) => void>();
const socket = {
    on: (event: { eventKey: string; callback: (data?: unknown) => void }) => callbacks.set(event.eventKey, event.callback),
    off: (event: { eventKey: string }) => callbacks.delete(event.eventKey),
} as unknown as import("@/core/providers/SocketProvider").ISocketContext;
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ url: config.url, method: config.method, data });
    if (params.has("delayed") && config.url?.includes("/board/project/signals/inbox")) await new Promise((resolve) => setTimeout(resolve, 400));
    if (config.method === "post" && params.has("error")) throw new Error("fixture mutation denied");
    if (config.method === "post") {
        if (data.resource_uid === "application" || data.resource_uid === "compose") linkedDeployments.add(data.resource_uid);
        else linked = true;
    }
    let result: unknown = { source_change_seq: 7, items: [], bindings: [] };
    if (config.url?.endsWith("/inbox"))
        result = {
            items:
                linked || config.url.includes("other")
                    ? []
                    : [
                          {
                              signal_uid: "signal",
                              provider: "github",
                              event_type: "check.completed",
                              can_bind_card: true,
                              resource_uid: "resource",
                              connection_uid: "connection",
                              external_id: "55",
                              commit_sha: "a".repeat(40),
                              outcome: "failure",
                              conflict: false,
                              occurred_at: "2026-10-08T00:00:00Z",
                          },
                      ],
            next_cursor: null,
        };
    if (params.has("mixed") && config.url?.endsWith("/inbox") && !config.url.includes("other")) {
        (result as { items: unknown[] }).items.push(
            ...["application", "compose"]
                .filter((type) => !linkedDeployments.has(type))
                .map((type) => ({
                    signal_uid: `dokploy-${type}`,
                    resource_uid: type,
                    connection_uid: "dokploy-connection",
                    provider: "dokploy",
                    resource_name: type === "application" ? "Customer API" : "Customer stack",
                    resource_type: type,
                    event_type: type === "compose" ? "deployment.failed" : "deployment.succeeded",
                    can_bind_card: !params.has("nonlink"),
                    external_id: `deployment-${type}`,
                    commit_sha: "",
                    outcome: type === "compose" ? "failure" : "success",
                    conflict: false,
                    occurred_at: "2026-10-08T00:00:00Z",
                }))
        );
    }
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
function Fixture() {
    const [board, setBoard] = useState("project");
    return (
        <main className="mx-auto h-screen max-w-md">
            <button onClick={() => setBoard("other")}>Switch board</button>
            <button
                onClick={() => {
                    for (let i = 0; i < 3; i++) callbacks.get(`signal-inbox-${board}`)?.({ app_signal_changed: true });
                }}
            >
                Signal burst
            </button>
            <SignalInboxPanel projectUID={board} socket={socket} canEdit={!params.has("readonly")} cards={[{ uid: "card", title: "Sample card" }]} />
        </main>
    );
}
void i18n.changeLanguage(params.get("lang") ?? "en-US").then(() => createRoot(document.getElementById("root")!).render(<Fixture />));
