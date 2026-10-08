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
const socket = { on: () => {}, off: () => {} } as unknown as import("@/core/providers/SocketProvider").ISocketContext;
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ url: config.url, method: config.method, data });
    if (config.method === "post" && params.has("error")) throw new Error("fixture mutation denied");
    if (config.method === "post") linked = true;
    let result: unknown = { source_change_seq: 7, items: [], bindings: [] };
    if (config.url?.endsWith("/inbox"))
        result = {
            items:
                linked || config.url.includes("other")
                    ? []
                    : [
                          {
                              signal_uid: "signal",
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
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
function Fixture() {
    const [board, setBoard] = useState("project");
    return (
        <main className="mx-auto h-screen max-w-md">
            <button onClick={() => setBoard("other")}>Switch board</button>
            <SignalInboxPanel projectUID={board} socket={socket} canEdit={!params.has("readonly")} cards={[{ uid: "card", title: "Sample card" }]} />
        </main>
    );
}
void i18n.changeLanguage(params.get("lang") ?? "en-US").then(() => createRoot(document.getElementById("root")!).render(<Fixture />));
