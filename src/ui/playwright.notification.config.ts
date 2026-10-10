import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/components/Header",
    testMatch: "notification-navigation.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4177", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4177 --strictPort",
        url: "http://127.0.0.1:4177/src/components/Header/notification-navigation.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
