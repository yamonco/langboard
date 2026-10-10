import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/BoardPage/components/board",
    testMatch: "BoardFilter.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4192", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4192 --strictPort",
        url: "http://127.0.0.1:4192/src/pages/BoardPage/components/board/BoardFilter.fixture.html",
        reuseExistingServer: true,
        timeout: 60000,
    },
});
