import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/SettingsPage",
    testMatch: "AppGovernance.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4216", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4216 --strictPort",
        url: "http://127.0.0.1:4216/src/pages/SettingsPage/AppGovernance.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
