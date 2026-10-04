import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

test("failed history request retries the same page and commits only successful results", async () => {
    const pages = [];
    const stored = [];
    let fail = true;
    const imports = {
        "@langboard/core/constants": { Routing: { API: { BOARD: { CHAT: { GET_MESSAGES: "/board/{uid}/chat/{session_uid}" } } } } },
        "@/core/helpers/Api": { api: { get: async (_url, { params }) => {
            pages.push(params.page);
            if (fail) { fail = false; throw new Error("temporary network failure"); }
            return { data: { histories: [{ uid: "message" }] } };
        } } },
        "@/core/helpers/QueryMutation": { useQueryMutation: () => ({ mutate: (_key, fn) => ({ mutateAsync: fn }) }) },
        "@/core/models": { ChatMessageModel: { Model: { getModel: () => ({}), fromArray: rows => stored.push(...rows) } } },
        "@langboard/core/utils": { Utils: { String: { format: (url, values) => url.replace(/\{(\w+)\}/g, (_, key) => values[key]) } } },
        react: { useRef: current => ({ current }), useState: initial => [initial, () => {}] },
    };
    const source = readFileSync(new URL("./useGetProjectChatMessages.ts", import.meta.url), "utf8");
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
    const exports = {};
    vm.runInNewContext(compiled, { exports, require: name => {
        assert.ok(name in imports, `Unexpected import: ${name}`);
        return imports[name];
    } });
    const reader = exports.default("board");
    await assert.rejects(reader.mutateAsync({ session_uid: "session" }));
    assert.equal(reader.pageRef.current, 0);
    await reader.mutateAsync({ session_uid: "session" });
    assert.deepEqual(pages, [1, 1]);
    assert.equal(reader.pageRef.current, 1);
    assert.equal(stored.length, 1);
});
