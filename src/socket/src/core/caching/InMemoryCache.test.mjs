import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { createRequire, Module } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import ts from "typescript";

const require = createRequire(import.meta.url);
const source = readFileSync(new URL("InMemoryCache.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;

function loadCache(directory) {
    const filename = path.join(directory, "cache-source.cjs");
    const loaded = new Module(filename);
    loaded.require = (name) => {
        if (name === "@/Constants") return { CACHE_DIR: directory };
        if (name === "@/core/caching/BaseCache") return { __esModule: true, default: class BaseCache {} };
        if (name === "@langboard/core/utils") return { Utils: { Json: { Parse: JSON.parse, Stringify: JSON.stringify } } };
        return require(name);
    };
    loaded._compile(compiled, filename);
    return loaded.exports.default;
}

test("fresh native cache accepts immediate reads and writes without initialization delays", async () => {
    for (let attempt = 0; attempt < 20; attempt++) {
        const directory = mkdtempSync(path.join(tmpdir(), "langboard-cache-startup-"));
        const Cache = loadCache(directory);
        const cache = new Cache();
        try {
            await cache.set("fresh", { attempt }, 60);
            assert.deepEqual(await cache.get("fresh"), { attempt });
            assert.equal(await cache.has("fresh"), true);
            await Promise.all(Array.from({ length: 10 }, (_, index) => cache.set(`key-${index}`, index, 60)));
            for (let index = 0; index < 10; index++) assert.equal(await cache.get(`key-${index}`), index);
            await cache.set("expired", "stale", -1);
            assert.equal(await cache.get("expired"), null);
            await cache.delete("fresh");
            assert.equal(await cache.has("fresh"), false);
            await cache.clear();
            assert.equal(await cache.get("key-0"), null);
        } finally {
            await cache.stop();
            rmSync(directory, { recursive: true, force: true });
        }
    }
});
