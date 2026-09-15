import { defineConfig } from "@playwright/test";

export default defineConfig({
    testDir: "./src/components/plate-ui",
    testMatch: "media-image-node.spec.ts",
    retries: 0,
    reporter: "line",
    use: { baseURL: "http://127.0.0.1:4176", channel: "chrome", headless: true },
    webServer: {
        command: "yarn vite --host 127.0.0.1 --port 4176 --strictPort",
        url: "http://127.0.0.1:4176/src/components/plate-ui/media-image-node.fixture.html",
        reuseExistingServer: false,
        timeout: 60_000,
    },
});
