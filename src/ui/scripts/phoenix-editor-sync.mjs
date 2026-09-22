import assert from "node:assert/strict";
import { HocuspocusProvider } from "@hocuspocus/provider";
import * as Y from "yjs";

const url = process.env.SOCKET_PHOENIX_TEST_URL;
const name = process.env.SOCKET_PHOENIX_TEST_DOCUMENT;
const phase = process.argv[2];
const expectedText = "Phoenix editor sync integration";

assert.ok(url && name, "The test URL and document name are required");
assert.ok(["write", "read", "expiry", "concurrent", "http-patch"].includes(phase), "Unknown editor sync test phase");

const providers = [];

function connect(document = new Y.Doc()) {
    const provider = new HocuspocusProvider({
        document,
        name,
        token: "test-token",
        url,
        WebSocketPolyfill: WebSocket,
    });
    providers.push(provider);
    return { document, provider };
}

async function waitFor(predicate, description) {
    const deadline = Date.now() + 10_000;
    while (!predicate()) {
        if (Date.now() >= deadline) {
            throw new Error(`Timed out waiting for ${description}`);
        }
        await new Promise((resolve) => setTimeout(resolve, 25));
    }
}

try {
    const first = connect();
    await waitFor(() => first.provider.isSynced, "the first provider to sync");

    if (phase === "write") {
        const second = connect();
        await waitFor(() => second.provider.isSynced, "the second provider to sync");

        first.document.getText("content").insert(0, expectedText);
        await waitFor(
            () => second.document.getText("content").toString() === expectedText,
            "the second provider to receive the update",
        );
        await waitFor(() => !first.provider.hasUnsyncedChanges, "the update acknowledgment");

        first.provider.awareness.setLocalStateField("user", { name: "first" });
        await waitFor(
            () => second.provider.awareness.getStates().has(first.document.clientID),
            "the peer awareness state",
        );

        first.provider.destroy();
        await waitFor(
            () => !second.provider.awareness.getStates().has(first.document.clientID),
            "awareness removal after disconnect",
        );
    } else if (phase === "http-patch") {
        const second = connect();
        await waitFor(() => second.provider.isSynced, "the second provider to sync");

        const patchUrl = new URL(url);
        patchUrl.protocol = patchUrl.protocol === "wss:" ? "https:" : "http:";
        patchUrl.pathname = "/editor-sync/text/patch";

        const response = await fetch(patchUrl, {
            method: "POST",
            headers: { "content-type": "application/json", "x-api-token": "test-internal-token" },
            body: JSON.stringify({ document_name: name, field: "content", value: expectedText }),
        });
        assert.equal(response.status, 200, await response.text());
        await waitFor(
            () =>
                first.document.getText("content").toString() === expectedText &&
                second.document.getText("content").toString() === expectedText,
            "both editors to receive the HTTP patch",
        );
    } else if (phase === "concurrent") {
        assert.equal(first.document.getText("content").toString(), "", "Use a new document for each conflict run");
        const otherDocument = new Y.Doc();
        const second = connect(otherDocument);
        first.document.getText("content").insert(0, "A");
        second.document.getText("content").insert(0, "B");
        await waitFor(() => second.provider.isSynced, "the second provider to sync");
        try {
            await waitFor(() => {
                const firstText = first.document.getText("content").toString();
                const secondText = second.document.getText("content").toString();
                return firstText === secondText && firstText.length === 2 && firstText.includes("A") && firstText.includes("B");
            }, "both conflicting edits to converge");
        } catch (error) {
            throw new Error(
                `Convergence failed: first=${first.document.getText("content")} second=${second.document.getText("content")}`,
                { cause: error },
            );
        }
        await waitFor(
            () => !first.provider.hasUnsyncedChanges && !second.provider.hasUnsyncedChanges,
            "both updates to be acknowledged",
        );
    } else if (phase === "expiry") {
        const second = connect();
        await waitFor(() => second.provider.isSynced, "the second provider to sync");
        const removed = [];
        second.provider.awareness.on("change", ({ removed: removedIds }) => removed.push(...removedIds));
        first.provider.awareness.setLocalStateField("user", { name: "first" });
        await waitFor(
            () => second.provider.awareness.getStates().has(first.document.clientID),
            "the peer awareness state",
        );
        await waitFor(
            () => removed.includes(first.document.clientID),
            "the awareness expiry event while the editor remains connected",
        );
        assert.equal(first.provider.isSynced, true);
    } else {
        await waitFor(
            () => first.document.getText("content").toString() === expectedText,
            "the persisted document to reload",
        );
    }

    console.log(`Phoenix editor sync ${phase} phase passed`);
} finally {
    for (const provider of providers) {
        provider.destroy();
    }
}
