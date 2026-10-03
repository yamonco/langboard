import { expect, test } from "@playwright/test";
for (const unfinished of [true, false]) {
    for (const count of [0, 3, 500]) {
        test(`workflow changes immediately refresh existing ${count} cards without losing order (unfinished=${unfinished})`, async ({ page }) => {
            const filters = unfinished ? "&filters=unfinished%3Ayes" : "";
            await page.goto(`/src/pages/BoardPage/components/board/WorkflowFilterRefresh.fixture.html?count=${count}${filters}`);
            const rows = page.getByRole("region", { name: "Results" }).locator("p");
            await expect(rows).toHaveCount(count);
            const initial = await rows.evaluateAll((elements) =>
                elements.map((element) => [element.getAttribute("data-card-uid"), element.getAttribute("data-order")])
            );
            for (let repetition = 0; repetition < 3; repetition++) {
                for (const stage of ["reference", "active", "closed", "", "ready"]) {
                    await page.getByRole("combobox", { name: "Stage" }).selectOption(stage);
                    await expect(rows).toHaveCount(unfinished && ["closed", "reference"].includes(stage) ? 0 : count);
                    if (!unfinished || !["closed", "reference"].includes(stage))
                        expect(
                            await rows.evaluateAll((elements) =>
                                elements.map((element) => [element.getAttribute("data-card-uid"), element.getAttribute("data-order")])
                            )
                        ).toEqual(initial);
                }
            }
            await page.reload();
            await expect(rows).toHaveCount(count);
        });
    }
}

test("projected completion updates reapply unfinished filters while retaining card identity and order", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/board/WorkflowFilterRefresh.fixture.html?count=500&filters=unfinished%3Ayes");
    const rows = page.getByRole("region", { name: "Results" }).locator("p");
    await expect(rows).toHaveCount(500);
    const initial = await rows.evaluateAll((elements) =>
        elements.map((element) => [element.getAttribute("data-card-uid"), element.getAttribute("data-order")])
    );
    for (let iteration = 0; iteration < 3; iteration++) {
        await page.getByRole("button", { name: "Toggle completion policy" }).click();
        await expect(rows).toHaveCount(0);
        await page.getByRole("button", { name: "Toggle completion policy" }).click();
        await expect(rows).toHaveCount(500);
        expect(
            await rows.evaluateAll((elements) =>
                elements.map((element) => [element.getAttribute("data-card-uid"), element.getAttribute("data-order")])
            )
        ).toEqual(initial);
    }
});
