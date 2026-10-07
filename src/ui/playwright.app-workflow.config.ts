import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src",
    testMatch: "AppWorkflow.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4197", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --host 127.0.0.1 --port 4197 --strictPort",
        url: "http://127.0.0.1:4197",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
