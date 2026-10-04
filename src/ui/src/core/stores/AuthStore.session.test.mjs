import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

test("real AuthStore fences stale identity success and failure after logout or replacement login", async () => {
    const directory = await mkdtemp(join(tmpdir(), "auth-session-test-"));
    try {
        const result = await build({
            entryPoints: [fileURLToPath(new URL("./AuthStore.ts", import.meta.url))],
            bundle: true, platform: "node", format: "esm", write: false,
            plugins: [{ name: "identity-boundaries", setup(build) {
                build.onResolve({ filter: /^@\/core\/(models|stores\/SocketStore)$/ }, (args) => ({ path: args.path, namespace: "test-boundary" }));
                build.onLoad({ filter: /.*/, namespace: "test-boundary" }, (args) => ({ contents: args.path.endsWith("models")
                    ? 'export const AuthUser = { Model: { fromOne: (user) => user } }; export const BotModel = { Model: { fromArray: () => {} } };'
                    : 'export default { getState: () => ({ close() {} }) };' }));
            } }],
        });
        const modulePath = join(directory, "store.mjs");
        await writeFile(modulePath, result.outputFiles[0].text);
        const { getAuthStore } = await import(pathToFileURL(modulePath));
        const deferred = () => {
            let resolve, reject;
            const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
            return { promise, resolve, reject };
        };
        const payload = (uid) => ({ data: { user: { uid }, bots: [] } });
        const old = deferred();
        const stale = getAuthStore().updateToken("synthetic-old", { get: () => old.promise });
        getAuthStore().removeToken();
        old.resolve(payload("old-user"));
        await stale;
        assert.equal(getAuthStore().currentUser, null);
        assert.equal(getAuthStore().getToken(), null);

        const failed = deferred();
        let reads = 0;
        const staleFailure = getAuthStore().updateToken("synthetic-old", { get: () => { reads++; return failed.promise; } });
        getAuthStore().removeToken();
        failed.reject(new Error("old-request-failed"));
        await staleFailure;
        assert.equal(reads, 1);

        const replaced = deferred();
        const first = getAuthStore().updateToken("synthetic-old", { get: () => replaced.promise });
        await getAuthStore().updateToken("synthetic-new", { get: async () => payload("new-user") });
        replaced.resolve(payload("old-user"));
        await first;
        assert.equal(getAuthStore().currentUser.uid, "new-user");
        assert.equal(getAuthStore().getToken(), "synthetic-new");
    } finally { await rm(directory, { recursive: true, force: true }); }
});
