import { createFilter, defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import dotenv from "dotenv";
import dns from "dns";
import fs from "fs";
import svgr from "vite-plugin-svgr";
import path from "path";

dns.setDefaultResultOrder("verbatim");

const EXPECTED_ENV_PATHS = ["../../../", "../../", "../", "./"];

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

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
    const isLocal = mode !== "production";
    for (let i = 0; i < EXPECTED_ENV_PATHS.length; ++i) {
        const envPath = path.join(EXPECTED_ENV_PATHS[i], ".env");
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

    let watchOptions = null;
    if (process.argv.includes("--watch") || process.argv.includes("-w")) {
        watchOptions = {
            exclude: ["**/node_modules/**", "**/.git/**"],
        };
    }

    return {
        plugins: [react(), tsconfigPaths(), svgr(), removeUseClient()],
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
