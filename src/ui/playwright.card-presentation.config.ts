import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/core/cards", testMatch: "CardPresentation.spec.ts", retries: 0, reporter: "line",
    use: { baseURL: "http://127.0.0.1:4207", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4207 --strictPort",
        url: "http://127.0.0.1:4207/src/core/cards/CardPresentation.fixture.html", reuseExistingServer: true, timeout: 60000,
    },
});
