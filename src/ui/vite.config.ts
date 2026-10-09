import { createFilter, defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import dotenv from "dotenv";
import dns from "dns";
import fs from "fs";
import svgr from "vite-plugin-svgr";
import path from "path";

dns.setDefaultResultOrder("verbatim");

// Resolve the repository env file from this config, not from process.cwd().
// Production builds are invoked from both the repository root and src/ui.
const EXPECTED_ENV_PATHS = ["../../.env", "../.env", "./.env", "../../../.env"];

const removeUseClient = () => {
    const filter = createFilter(/.*\.(js|ts|jsx|tsx)$/);

    return {
        name: "remove-use-client",

        transform(code: string, id: string) {
            if (!filter(id)) {
                return null;
            }

            const newCode = code.replace(/['"]use client['"];\s*/g, "");

            return { code: newCode, map: null };
        },
    };
};

// Publish actual compiled widgets and the existing generated UI stylesheet.
const panelSDKResources = (): Plugin => ({
    name: "panel-sdk-resources",
    configureServer(server) {
        // Opaque panel documents cannot run React Refresh source transforms.
        // Development reuses a prior compiled widget entry and its shared CSS.
        const output = path.resolve(server.config.root, server.config.build.outDir);
        server.middlewares.use((request, response, next) => {
            const pathname = request.url?.split("?")[0];
            if (pathname !== "/panel-sdk-resources.json" && !pathname?.startsWith("/panel-sdk-assets/")) return next();
            response.setHeader("Access-Control-Allow-Origin", "*");
            if (pathname === "/panel-sdk-resources.json") {
                try {
                    const manifest = JSON.parse(fs.readFileSync(path.join(output, "panel-sdk-resources.json"), "utf8"));
                    response.setHeader("Content-Type", "application/json");
                    response.setHeader("Cache-Control", "no-cache");
                    response.end(
                        JSON.stringify({
                            ...manifest,
                            module_url: manifest.module_url.replace("/assets/", "/panel-sdk-assets/"),
                            css_url: manifest.css_url.replace("/assets/", "/panel-sdk-assets/"),
                        })
                    );
                } catch {
                    response.statusCode = 503;
                    response.end("Build the UI once to provide compiled panel widgets.");
                }
                return;
            }
            const name = pathname?.slice("/panel-sdk-assets/".length) ?? "";
            if (!/^[A-Za-z0-9_.-]+\.(js|css)$/.test(name)) {
                response.statusCode = 404;
                response.end();
                return;
            }
            const file = path.join(output, "assets", name);
            if (!fs.existsSync(file)) {
                response.statusCode = 404;
                response.end();
                return;
            }
            response.setHeader("Content-Type", name.endsWith(".css") ? "text/css" : "text/javascript");
            response.setHeader("Cache-Control", "public, max-age=31536000, immutable");
            fs.createReadStream(file).pipe(response);
        });
    },
    generateBundle(_options, bundle) {
        const module = Object.values(bundle).find(
            (entry) => entry.type === "chunk" && entry.isEntry && entry.facadeModuleId?.endsWith("/core/apps/widgets.tsx")
        );
        const styles = Object.values(bundle).filter(
            (entry) =>
                entry.type === "asset" &&
                entry.fileName.endsWith(".css") &&
                String(entry.source).includes("--background:") &&
                String(entry.source).includes("--primary:")
        );
        if (!module || styles.length !== 1) throw new Error("Panel SDK requires its widget entry and one shared semantic stylesheet");
        this.emitFile({
            type: "asset",
            fileName: "panel-sdk-resources.json",
            source: JSON.stringify({ version: 1, module_url: `/${module.fileName}`, css_url: `/${styles[0].fileName}` }),
        });
    },
});

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isLocal = mode !== "production";
    for (let i = 0; i < EXPECTED_ENV_PATHS.length; ++i) {
        const envPath = path.resolve(__dirname, EXPECTED_ENV_PATHS[i]);
        if (fs.existsSync(envPath)) {
            dotenv.config({ path: envPath });
            break;
        }
    }
    EXPECTED_ENV_PATHS.splice(0);

    const PORT = Number(process.env.UI_PORT) || 5173;

    const UI_SERVER = `http://localhost:${PORT}`;
    const API_SERVER = `http://localhost:${process.env.API_PORT}`;
    const SOCKET_SERVER = `http://localhost:${process.env.SOCKET_PORT}`;

    if (mode === "production") {
        for (const key of ["API_URL", "PUBLIC_UI_URL", "SOCKET_URL"]) {
            if (!process.env[key]) {
                throw new Error(`${key} is required for a production UI build`);
            }
        }
    }

    let watchOptions = null;
    if (process.argv.includes("--watch") || process.argv.includes("-w")) {
        watchOptions = {
            exclude: ["**/node_modules/**", "**/.git/**"],
        };
    }

    return {
        plugins: [react(), tsconfigPaths(), svgr(), removeUseClient(), panelSDKResources()],
        resolve: {
            alias: {
                "@": path.resolve(__dirname, "./src"),
            },
        },
        define: {
            "process.env.IS_PRODUCTION": JSON.stringify(String(mode === "production")),
            "process.env.PROJECT_NAME": JSON.stringify(process.env.PROJECT_NAME),
            "process.env.PROJECT_SHORT_NAME": JSON.stringify(process.env.PROJECT_SHORT_NAME),
            "process.env.API_URL": JSON.stringify(isLocal ? API_SERVER : process.env.API_URL),
            "process.env.PUBLIC_UI_URL": JSON.stringify(isLocal ? UI_SERVER : process.env.PUBLIC_UI_URL),
            "process.env.SOCKET_URL": JSON.stringify(isLocal ? SOCKET_SERVER : process.env.SOCKET_URL),
            "process.env.IS_OLLAMA_RUNNING": JSON.stringify(process.env.IS_OLLAMA_RUNNING || (process.env.OLLAMA_API_URL ? "true" : "false")),
            "process.env.MAX_FILE_SIZE_MB": JSON.stringify(process.env.MAX_FILE_SIZE_MB || 50),
        },
        build: {
            manifest: true,
            rollupOptions: {
                input: { main: path.resolve(__dirname, "index.html"), "panel-widgets": path.resolve(__dirname, "src/core/apps/widgets.tsx") },
                preserveEntrySignatures: "strict",
            },
            // Keep content-hashed assets from the previous deployment so an
            // already-open client can still lazy-load its remaining chunks.
            // index.html is replaced on every build and is served no-cache.
            emptyOutDir: false,
            watch: watchOptions,
            chunkSizeWarningLimit: 2000,
        },
        server: {
            host: true,
            port: PORT,
            strictPort: true,
        },
        optimizeDeps: {
            include: ["react/jsx-runtime", "papaparse"],
            exclude: ["@langboard/core"],
        },
    };
});
