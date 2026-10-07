import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src",
    testMatch: "GitHubOnboarding.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4198", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --host 127.0.0.1 --port 4198 --strictPort",
        url: "http://127.0.0.1:4198",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
