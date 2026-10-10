import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/core/providers",
    testMatch: "NotificationLoad.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4209", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4209 --strictPort",
        url: "http://127.0.0.1:4209/src/core/providers/NotificationLoad.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
