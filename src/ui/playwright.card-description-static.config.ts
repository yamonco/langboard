import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/pages/BoardPage/components/card/description",
    testMatch: "board-card-description-static.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4179", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4179 --strictPort",
        url: "http://127.0.0.1:4179/src/pages/BoardPage/components/card/description/board-card-description-static.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
