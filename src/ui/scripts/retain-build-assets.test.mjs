import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { prepareRetention, pruneAssets } from "./retain-build-assets.mjs";

async function fixture() {
    const distDir = await mkdtemp(path.join(os.tmpdir(), "langboard-assets-"));
    await mkdir(path.join(distDir, ".vite"), { recursive: true });
    await mkdir(path.join(distDir, "assets"), { recursive: true });
    await writeFile(path.join(distDir, "assets", "previous.js"), "previous");
    await writeFile(path.join(distDir, "assets", "current.js"), "current");
    await writeFile(path.join(distDir, "assets", "stale.js"), "stale");
    await writeFile(path.join(distDir, ".vite", "manifest.json"), JSON.stringify({ app: { file: "assets/previous.js" } }));
    return distDir;
}

test("keeps current and previous release assets while pruning stale files", async () => {
    const distDir = await fixture();
    assert.equal(await prepareRetention(distDir), true);
    await writeFile(path.join(distDir, ".vite", "manifest.json"), JSON.stringify({ app: { file: "assets/current.js" } }));

    const dryRun = await pruneAssets(distDir);
    assert.deepEqual(dryRun.candidates, ["stale.js"]);
    assert.equal(await readFile(path.join(distDir, "assets", "stale.js"), "utf8"), "stale");

    await pruneAssets(distDir, true);
    await assert.rejects(readFile(path.join(distDir, "assets", "stale.js")), { code: "ENOENT" });
    assert.equal(await readFile(path.join(distDir, "assets", "previous.js"), "utf8"), "previous");
    assert.equal(await readFile(path.join(distDir, "assets", "current.js"), "utf8"), "current");
});

test("skips deletion when no previous release manifest exists", async () => {
    const distDir = await fixture();
    const result = await pruneAssets(distDir, true);
    assert.equal(result.skipped, true);
    assert.equal(await readFile(path.join(distDir, "assets", "stale.js"), "utf8"), "stale");
});
