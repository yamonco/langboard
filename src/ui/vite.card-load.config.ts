import { defineConfig, mergeConfig, type UserConfigFnObject } from "vite";
import base from "./vite.config";
import { createRequire } from "node:module";
import { dirname } from "node:path";

const require = createRequire(import.meta.url);
// Shared worktree dependencies can contain another React version at their root.
const rendererRoot = dirname(require.resolve("react-dom/package.json"));
const rendererReact = dirname(require.resolve("react/package.json", { paths: [rendererRoot] }));

export default defineConfig((env) =>
    mergeConfig((base as UserConfigFnObject)(env), {
        cacheDir: "node_modules/.vite-card-load",
        resolve: { alias: { react: rendererReact }, dedupe: ["react", "react-dom", "react-router", "@tanstack/react-query"] },
    })
);
