import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/components/Layout",
    testMatch: "workbench-shell.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4183", channel: "chrome", headless: true },
    webServer: {
        command: "API_PORT=5381 node_modules/.bin/vite --config vite.card-load.config.ts --host 127.0.0.1 --port 4183 --strictPort",
        url: "http://127.0.0.1:4183/src/components/Layout/workbench-shell.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
