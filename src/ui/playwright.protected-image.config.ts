import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/components/CachedImage",
    testMatch: "protected-image.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4219", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4219 --strictPort",
        url: "http://127.0.0.1:4219/src/components/CachedImage/protected-image.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
