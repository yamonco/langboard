import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/SettingsPage",
    testMatch: "WorkflowStages.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4194", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4194 --strictPort",
        url: "http://127.0.0.1:4194/src/pages/SettingsPage/WorkflowStages.fixture.html",
        reuseExistingServer: true,
        timeout: 60000,
    },
});
