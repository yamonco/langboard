import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/pages/BoardPage/components/board",
    testMatch: "CardViewerDeepLink.spec.ts",
    fullyParallel: true,
    retries: 0,
    reporter: "line",
    use: {
        baseURL: "http://127.0.0.1:4175",
        browserName: "chromium",
        channel: "chrome",
        headless: true,
        viewport: { width: 1280, height: 800 },
    },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4175 --strictPort",
        url: "http://127.0.0.1:4175/src/pages/BoardPage/components/board/CardViewerDeepLink.fixture.html",
        reuseExistingServer: true,
        timeout: 60_000,
    },
});
