import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src",
    testMatch: ["refreshProjectColumnDock.spec.ts", "Api.auth.spec.ts"],
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4181", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4181 --strictPort",
        url: "http://127.0.0.1:4181/src/controllers/api/board/refreshProjectColumnDock.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
