import { defineConfig } from "@playwright/test";
export default defineConfig({
 testDir: "./src/core/providers", testMatch: "board-chat-stability.spec.ts", retries: 0, reporter: "line",
 use: { baseURL: "http://127.0.0.1:4196", channel: "chrome", headless: true },
 webServer: { command: "API_PORT=5381 node_modules/.bin/vite --config vite.board-chat-stability.config.ts --host 127.0.0.1 --port 4196 --strictPort", url: "http://127.0.0.1:4196", reuseExistingServer: false },
});
