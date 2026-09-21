import { copyFile, mkdir, readFile, readdir, rm, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const uiDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultDistDir = path.join(uiDir, "dist");
const manifestPath = (distDir) => path.join(distDir, ".vite", "manifest.json");
const previousManifestPath = (distDir) => path.join(distDir, ".vite", "manifest.previous.json");

async function readJson(filename) {
    return JSON.parse(await readFile(filename, "utf8"));
}

export function collectManifestAssets(manifest) {
    const assets = new Set();
    for (const entry of Object.values(manifest)) {
        for (const filename of [entry.file, ...(entry.css || []), ...(entry.assets || [])]) {
            if (filename?.startsWith("assets/")) {
                assets.add(filename);
            }
        }
    }
    return assets;
}

async function listFiles(directory, root = directory) {
    const files = [];
    for (const entry of await readdir(directory, { withFileTypes: true })) {
        const filename = path.join(directory, entry.name);
        if (entry.isDirectory()) {
            files.push(...(await listFiles(filename, root)));
        } else if (entry.isFile()) {
            files.push(path.relative(root, filename));
        }
    }
    return files;
}

export async function prepareRetention(distDir = defaultDistDir) {
    try {
        await mkdir(path.dirname(previousManifestPath(distDir)), { recursive: true });
        await copyFile(manifestPath(distDir), previousManifestPath(distDir));
        return true;
    } catch (error) {
        if (error.code === "ENOENT") {
            return false;
        }
        throw error;
    }
}

export async function pruneAssets(distDir = defaultDistDir, deleteFiles = false) {
    const current = await readJson(manifestPath(distDir));
    let previous;
    try {
        previous = await readJson(previousManifestPath(distDir));
    } catch (error) {
        if (error.code === "ENOENT") {
            return { skipped: true, reason: "previous manifest is unavailable", candidates: [], bytes: 0 };
        }
        throw error;
    }

    const protectedAssets = new Set([...collectManifestAssets(current), ...collectManifestAssets(previous)]);
    if (!protectedAssets.size) {
        throw new Error("refusing to prune without protected manifest assets");
    }

    const assetsDir = path.join(distDir, "assets");
    const candidates = (await listFiles(assetsDir)).filter((filename) => !protectedAssets.has(`assets/${filename}`));
    let bytes = 0;
    for (const filename of candidates) {
        const fullPath = path.join(assetsDir, filename);
        bytes += (await stat(fullPath)).size;
        if (deleteFiles) {
            await rm(fullPath);
        }
    }
    return { skipped: false, candidates, bytes };
}

async function main() {
    const [command, flag] = process.argv.slice(2);
    if (command === "prepare") {
        const preserved = await prepareRetention();
        console.log(preserved ? "Preserved current manifest as previous release." : "No prior manifest; pruning will be skipped.");
        return;
    }
    if (command === "prune") {
        const result = await pruneAssets(defaultDistDir, flag === "--delete");
        console.log(JSON.stringify({ ...result, candidates: result.candidates.length }));
        return;
    }
    throw new Error("usage: retain-build-assets.mjs prepare | prune [--delete]");
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
    await main();
}
