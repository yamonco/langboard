import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/pages/BoardPage/components/card/comment",
    testMatch: "commentAnchor.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4178", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4178 --strictPort",
        url: "http://127.0.0.1:4178/src/pages/BoardPage/components/card/comment/commentAnchor.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
