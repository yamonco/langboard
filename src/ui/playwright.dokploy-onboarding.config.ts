import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src",
    testMatch: "DokployOnboarding.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4249", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --host 127.0.0.1 --port 4249 --strictPort",
        url: "http://127.0.0.1:4249",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
