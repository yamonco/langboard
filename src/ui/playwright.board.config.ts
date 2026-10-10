import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/pages/BoardPage/components/board",
    testMatch: "BoardTouchDnd.spec.ts",
    fullyParallel: true,
    retries: 0,
    reporter: "line",
    use: {
        baseURL: "http://127.0.0.1:4174",
        browserName: "chromium",
        channel: "chrome",
        headless: true,
        hasTouch: true,
        viewport: { width: 390, height: 844 },
    },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4174 --strictPort",
        url: "http://127.0.0.1:4174/src/pages/BoardPage/components/board/BoardTouchDnd.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
