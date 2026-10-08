import { createRoot } from "react-dom/client";
import { useState } from "react";
import CardSignalEvidence from "./CardSignalEvidence";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const params = new URLSearchParams(location.search);
const calls: { url?: string; method?: string; data: unknown }[] = [];
Object.assign(window, { evidenceCalls: calls });
const listeners = new Set<{ event: string; callback: (data: unknown) => void }>();
const socket = {
    on: (entry: { event: string; callback: (data: unknown) => void }) => {
        listeners.add(entry);
    },
    off: (entry: { event: string; callback: (data: unknown) => void }) => {
        listeners.delete(entry);
    },
};
const emit = (event: string, data: unknown) =>
    listeners.forEach((entry) => {
        if (entry.event === event) entry.callback(data);
    });
let outcome = "passed";
let linked = !params.has("empty");
let revision = 0;
const unlinkedDeployments = new Set<string>();
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ url: config.url, method: config.method, data });
    if (params.has("delayed") && config.url === "/board/project/card/card/signals") await new Promise((resolve) => setTimeout(resolve, 400));
    if (params.has("error") && config.method === "post") throw new Error("fixture failure");
    if (config.url?.endsWith("/unlink")) {
        if (config.url.includes("/deployment-")) unlinkedDeployments.add(config.url.split("/").at(-2)!);
        else linked = false;
        revision++;
    } else if (config.method === "post") {
        linked = true;
        revision++;
    }
    let result: unknown = { items: [], bindings: [], source_change_seq: 7 };
    if (config.url?.endsWith("/resources"))
        result = {
            items: [{ uid: "resource", connection_uid: "connection", name: "sample/repository" }],
        };
    else if (config.url?.includes("/settings/"))
        result = { items: [{ signal_uid: "signal", external_id: "55", commit_sha: "a".repeat(40), outcome: "success" }], next_cursor: null };
    else if (config.method === "get")
        result = {
            source_change_seq: 7,
            bindings: linked ? [{ binding_uid: "binding", revision }] : [],
            items:
                linked && !params.has("revoked")
                    ? [
                          {
                              binding_uid: "binding",
                              provider: "github",
                              event_type: "check.completed",
                              revision,
                              state: outcome,
                              resource_uid: "resource",
                              external_id: "55",
                              commit_sha: "a".repeat(40),
                              occurred_at: "2026-10-08T00:00:00Z",
                          },
                      ]
                    : [],
        };
    if (params.has("mixed") && config.method === "get" && !config.url?.includes("/settings/") && !config.url?.endsWith("/resources")) {
        const snapshot = result as { items: unknown[]; bindings: unknown[] };
        if (config.url?.includes("/card/other/")) {
            snapshot.items = [];
            snapshot.bindings = [];
        } else
            for (const [type, state] of [
                ["application", params.get("state") ?? "passed"],
                ["compose", "running"],
            ]) {
                const uid = `deployment-${type}`;
                if (unlinkedDeployments.has(uid)) continue;
                snapshot.bindings.push({ binding_uid: uid, revision: 3 });
                snapshot.items.push({
                    binding_uid: uid,
                    revision: 3,
                    state,
                    provider: "dokploy",
                    event_type: type === "compose" ? "deployment.started" : "deployment.succeeded",
                    resource_name: type === "compose" ? "Customer stack" : "Customer API",
                    resource_type: type,
                    resource_uid: type,
                    external_id: `actual-${type}-deployment`,
                    commit_sha: "",
                    occurred_at: "2026-10-08T00:00:00Z",
                });
            }
    }
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
function Fixture() {
    const [card, setCard] = useState("card");
    const [cardRevision, setCardRevision] = useState(7);
    return (
        <main className="mx-auto max-w-xl p-4">
            <button onClick={() => setCard("other")}>Switch card</button>
            <button
                onClick={() => {
                    outcome = "failed";
                    for (let i = 0; i < 30; i++) emit("board:app-signal:changed", { app_signal_changed: true });
                }}
            >
                Signal burst
            </button>
            <button onClick={() => emit("open", {})}>Reconnect</button>
            <button onClick={() => window.dispatchEvent(new Event("focus"))}>Return to window</button>
            <button onClick={() => setCardRevision((value) => value + 1)}>Edit card</button>
            <CardSignalEvidence
                socket={socket as unknown as import("@/core/providers/SocketProvider").ISocketContext}
                projectUID="project"
                cardUID={card}
                cardRevision={cardRevision}
                canEdit={!params.has("readonly")}
            />
        </main>
    );
}
void i18n.changeLanguage(params.get("lang") ?? "en-US").then(() => createRoot(document.getElementById("root")!).render(<Fixture />));
