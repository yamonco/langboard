import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src/components/Editor",
    testMatch: "table-selection.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4185", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4185 --strictPort",
        url: "http://127.0.0.1:4185/src/components/Editor/table-selection.fixture.html",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
