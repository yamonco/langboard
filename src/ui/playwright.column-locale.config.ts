import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/BoardPage/components/board",
    testMatch: "BoardColumnLocale.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4203", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4203 --strictPort",
        url: "http://127.0.0.1:4203/src/pages/BoardPage/components/board/BoardColumnLocale.fixture.html",
        reuseExistingServer: true,
        timeout: 60000,
    },
});
