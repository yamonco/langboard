import { test, expect } from "@playwright/test";
for (const width of [1280, 390])
    test(`global label translations persist at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        let labels: object[] = [];
        await page.route("**/settings/global-labels**", async (route) => {
            const headers = {
                "Access-Control-Allow-Origin": "http://127.0.0.1:4193",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
                "Access-Control-Allow-Headers": "content-type,authorization,content-encoding",
            };
            if (route.request().method() === "OPTIONS") return route.fulfill({ status: 204, headers });
            if (route.request().method() === "GET") return route.fulfill({ headers, json: { labels } });
            const label = { ...route.request().postDataJSON(), uid: "saved" };
            labels = [label];
            return route.fulfill({ headers, json: { label } });
        });
        await page.goto("/src/pages/SettingsPage/GlobalLabels.fixture.html");
        await expect(page.getByText("No global labels yet")).toBeVisible();
        await page.getByLabel("Label name", { exact: true }).fill("Request");
        await page.getByLabel("Label description", { exact: true }).fill("English guidance");
        await page.getByRole("button", { name: "한국어", exact: true }).click();
        await page.getByLabel("Label name", { exact: true }).fill("요청");
        await page.getByLabel("Label description", { exact: true }).fill("한국어 설명");
        await page.getByRole("button", { name: "English", exact: true }).click();
        await expect(page.getByLabel("Label name", { exact: true })).toHaveValue("Request");
        await page.getByLabel("Language code", { exact: true }).fill("fr");
        await page.getByRole("button", { name: "Add language", exact: true }).click();
        await page.getByLabel("Label name", { exact: true }).fill("Demande");
        await page.getByRole("button", { name: "Save", exact: true }).click();
        await expect(page.getByRole("navigation").getByRole("button", { name: "Request", exact: true })).toBeVisible();
        await page.reload();
        await page.getByRole("navigation").getByRole("button", { name: "Request", exact: true }).click();
        await page.getByRole("button", { name: "한국어", exact: true }).click();
        await expect(page.getByLabel("Label name", { exact: true })).toHaveValue("요청");
        await expect(page.getByLabel("Label description", { exact: true })).toHaveValue("한국어 설명");
        await page.getByRole("button", { name: "fr", exact: true }).click();
        await expect(page.getByLabel("Label name", { exact: true })).toHaveValue("Demande");
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    });
