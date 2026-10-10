import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/BoardPage/components/chat",
    testMatch: "history-recovery.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4195", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.chat-recovery.config.ts --host 127.0.0.1 --port 4195 --strictPort",
        url: "http://127.0.0.1:4195",
        reuseExistingServer: false,
    },
});
