import { defineConfig, mergeConfig, type UserConfigFnObject } from "vite";
import base from "./vite.card-load.config";
import path from "node:path";
const boundary = path.resolve(__dirname, "src/core/providers/board-chat-stability.boundary.ts");
export default defineConfig((env) =>
    mergeConfig((base as UserConfigFnObject)(env), {
        cacheDir: "node_modules/.vite-board-chat-stability",
        // Transform the fixture before interaction so cold dependency discovery does not reload its document.
        server: { warmup: { clientFiles: ["./src/core/providers/board-chat-stability.fixture.tsx"] } },
        optimizeDeps: { entries: ["src/core/providers/board-chat-stability.fixture.html"] },
        resolve: {
            alias: [
                { find: "@/core/providers/AuthProvider", replacement: boundary },
                { find: "@/core/providers/SocketProvider", replacement: boundary },
                { find: "@/components/Collaborative/useCollaborativeText", replacement: boundary },
            ],
        },
    })
);
