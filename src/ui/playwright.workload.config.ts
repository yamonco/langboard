import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/DashboardPage/components",
    testMatch: "workload.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4186", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4186 --strictPort",
        url: "http://127.0.0.1:4186/src/pages/DashboardPage/components/workload.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
