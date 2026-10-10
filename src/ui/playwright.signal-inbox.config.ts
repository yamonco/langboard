import { defineConfig } from "@playwright/test";
export default defineConfig({
    testDir: "./src",
    testMatch: "SignalInboxPanel.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4238", channel: "chrome", headless: true },
    webServer: {
        command: "node_modules/.bin/vite --host 127.0.0.1 --port 4238 --strictPort",
        url: "http://127.0.0.1:4238",
        reuseExistingServer: false,
        timeout: 60000,
    },
});
