import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/controllers/api/board",
    testMatch: "useGetProject.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4185", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4185 --strictPort",
        url: "http://127.0.0.1:4185/src/controllers/api/board/useGetProject.fixture.html",
        reuseExistingServer: true,
        timeout: 60_000,
    },
});
