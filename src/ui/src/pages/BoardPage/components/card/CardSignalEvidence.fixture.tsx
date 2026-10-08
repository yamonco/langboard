import { createRoot } from "react-dom/client";
import { useState } from "react";
import CardSignalEvidence from "./CardSignalEvidence";
import { api } from "@/core/helpers/Api";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const params = new URLSearchParams(location.search);
const calls: { url?: string; method?: string; data: unknown }[] = [];
Object.assign(window, { evidenceCalls: calls });
let linked = !params.has("empty");
let revision = 0;
api.defaults.adapter = async (config) => {
    const data = config.data ? JSON.parse(config.data) : null;
    calls.push({ url: config.url, method: config.method, data });
    if (params.has("error") && config.method === "post") throw new Error("fixture failure");
    if (config.url?.endsWith("/unlink")) {
        linked = false;
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
                              revision,
                              state: "passed",
                              resource_uid: "resource",
                              external_id: "55",
                              commit_sha: "a".repeat(40),
                              occurred_at: "2026-10-08T00:00:00Z",
                          },
                      ]
                    : [],
        };
    return { config, status: 200, statusText: "OK", headers: {}, data: result };
};
function Fixture() {
    const [card, setCard] = useState("card");
    return (
        <main className="mx-auto max-w-xl p-4">
            <button onClick={() => setCard("other")}>Switch card</button>
            <CardSignalEvidence projectUID="project" cardUID={card} canEdit={!params.has("readonly")} />
        </main>
    );
}
void i18n.changeLanguage(params.get("lang") ?? "en-US").then(() => createRoot(document.getElementById("root")!).render(<Fixture />));
