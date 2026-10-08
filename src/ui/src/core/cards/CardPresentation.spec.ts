import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { parseCardPresentation, cardPresentationText, cardVisibilityPresentation } from "./CardPresentation";
const load = (locale: string) => JSON.parse(readFileSync(new URL(`../../assets/locales/${locale}/card.json`, import.meta.url), "utf8"));
const [en, ko, ja, zh] = ["en-US", "ko-KR", "ja-JP", "zh-CN"].map(load);
for (const [locale, texts] of Object.entries({ "en-US": en, "ko-KR": ko, "ja-JP": ja, "zh-CN": zh })) {
    test(`${locale} visibility badge shows localized hover and keyboard description`, async ({ page }) => {
        await page.goto("/src/core/cards/CardPresentation.fixture.html");
        await page.getByRole("combobox", { name: "Language" }).selectOption(locale);
        const badge = page.locator("[data-card-presentation=visibility\\.whisper]").first();
        await expect(badge).toContainText(texts.Whisper);
        await badge.hover();
        await expect(page.getByRole("tooltip")).toHaveText(texts["Whisper visibility guidance"]);
        await page.mouse.move(0, 0);
        await badge.focus();
        await expect(page.getByRole("tooltip")).toHaveText(texts["Whisper visibility guidance"]);
        await page.keyboard.press("Escape");
        await expect(page.getByRole("tooltip")).toHaveCount(0);
        await page.setViewportSize({ width: 390, height: 844 });
        await badge.focus();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}

test("extension kinds use locale fallback and cannot override native privacy or policy", () => {
    const item = {
        version: 1,
        key: "app.glitchtip.issue",
        axis: "origin",
        name: "GlitchTip issue",
        description: "App origin.",
        translations: { ko: { name: "오류 카드", description: "앱에서 만든 카드입니다." } },
    };
    const parsed = parseCardPresentation(JSON.stringify(item))!;
    expect(cardPresentationText(parsed, "ko-KR").name).toBe("오류 카드");
    expect(cardPresentationText(parsed, "fr-FR").name).toBe("GlitchTip issue");
    for (const change of [
        { axis: "visibility" },
        { key: "visibility.private" },
        { visibility: "SHARED" },
        { completed: true },
        { translations: [] },
        { icon: "x".repeat(33) },
    ]) {
        expect(parseCardPresentation(JSON.stringify({ ...item, ...change }))).toBeUndefined();
    }
    expect(parseCardPresentation("invalid")).toBeUndefined();
    expect(cardVisibilityPresentation("PRIVATE", true)).toBe("private");
    expect(cardVisibilityPresentation("INTERNAL", true)).toBe("whisper");
    expect(cardVisibilityPresentation("INTERNAL", false)).toBeUndefined();
    expect(cardVisibilityPresentation("SHARED", true)).toBeUndefined();
});

test("SDK metadata updates the common badge without replacing visibility", async ({ page }) => {
    await page.goto("/src/core/cards/CardPresentation.fixture.html");
    await page.getByRole("combobox", { name: "Language" }).selectOption("ko-KR");
    await page.getByRole("button", { name: "Attach app type" }).click();
    const appBadge = page.locator("[data-card-presentation-axis=origin]");
    await expect(appBadge).toHaveText("🔗깃허브 이슈");
    await expect(page.locator("[data-card-presentation-axis=visibility]").first()).toContainText("귓속말");
    await appBadge.hover();
    await expect(page.getByRole("tooltip")).toHaveText("앱에서 제공한 출처입니다.");
    await page.getByRole("button", { name: "Remove app type" }).click();
    await expect(appBadge).toHaveCount(0);
    await expect(page.locator("[data-card-presentation-axis=visibility]").first()).toContainText("귓속말");
});

for (const width of [1920, 390]) {
    test(`native visibility follows project member transitions without changing card values at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width, height: 844 });
        await page.goto("/src/core/cards/CardPresentation.fixture.html");
        await page.getByRole("combobox", { name: "Language" }).selectOption("ko-KR");
        const internal = page.getByTestId("internal-card");
        const privateCard = page.getByTestId("private-card");
        await expect(internal.locator("[data-card-presentation-axis=visibility]")).toHaveCount(0);
        await expect(privateCard).toContainText("프라이빗");
        await page.getByRole("button", { name: "Add external member" }).click();
        await expect(internal).toContainText("귓속말");
        await expect(privateCard).toContainText("프라이빗");
        await expect(page.getByTestId("stored-visibility")).toHaveText("INTERNAL");
        await internal.locator("[data-card-presentation-axis=visibility]").hover();
        await expect(page.getByRole("tooltip")).toHaveText(ko["Whisper visibility guidance"]);
        await page.getByRole("button", { name: "Remove external member" }).click();
        await expect(internal.locator("[data-card-presentation-axis=visibility]")).toHaveCount(0);
        await expect(privateCard).toContainText("프라이빗");
        await expect(page.getByTestId("stored-visibility")).toHaveText("INTERNAL");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    });
}
