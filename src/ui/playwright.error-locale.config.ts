import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/core/helpers",
    testMatch: "ApiErrorLocale.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4201", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4201 --strictPort",
        url: "http://127.0.0.1:4201/src/core/helpers/ApiErrorLocale.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
