import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/DashboardPage/components",
    testMatch: "recent-cards.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4188", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4188 --strictPort",
        url: "http://127.0.0.1:4188/src/pages/DashboardPage/components/recent-cards.fixture.html",
        reuseExistingServer: true,
        timeout: 60000,
    },
});
