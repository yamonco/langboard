import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/DashboardPage/components",
    testMatch: "TemplateSelection.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4210", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4210 --strictPort",
        url: "http://127.0.0.1:4210/src/pages/DashboardPage/components/TemplateSelection.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
