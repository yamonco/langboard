import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/DashboardPage/components",
    testMatch: "explorer-recovery.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4193", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4193 --strictPort",
        url: "http://127.0.0.1:4193/src/pages/DashboardPage/components/explorer-recovery.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
