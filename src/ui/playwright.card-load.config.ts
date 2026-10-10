import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/pages/BoardPage/components/card",
    testMatch: "card-load.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4184", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4184 --strictPort",
        url: "http://127.0.0.1:4184/src/pages/BoardPage/components/card/card-load.fixture.html",
        reuseExistingServer: true,
        timeout: 60_000,
    },
});
