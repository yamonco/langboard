import { defineConfig, mergeConfig, type UserConfigFnObject } from "vite";
import base from "./vite.card-load.config";
import path from "node:path";
const boundary = path.resolve(__dirname, "src/pages/BoardPage/components/chat/history-recovery.boundary.tsx");
export default defineConfig((env) =>
    mergeConfig((base as UserConfigFnObject)(env), {
        optimizeDeps: { entries: ["src/pages/BoardPage/components/chat/history-recovery.fixture.html"] },
        cacheDir: "node_modules/.vite-chat-recovery",
        resolve: {
            alias: [
                { find: "@/core/providers/BoardChatProvider", replacement: boundary },
                { find: "@/controllers/api/board/chat/useGetProjectChatMessages", replacement: boundary + "?history" },
                { find: "@/pages/BoardPage/components/chat/ChatMessage", replacement: boundary + "?message" },
                { find: /^@\/core\/models$/, replacement: boundary },
            ],
        },
        plugins: [
            {
                name: "fixture-defaults",
                transform(code, id) {
                    if (id.endsWith("history-recovery.boundary.tsx?history")) return code + "\nexport default useHistory;";
                    if (id.endsWith("history-recovery.boundary.tsx?message")) return code + "\nexport default ChatMessage;";
                },
            },
        ],
    }),
);
