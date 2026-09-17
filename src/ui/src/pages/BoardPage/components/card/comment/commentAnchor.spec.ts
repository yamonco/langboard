import { expect, test } from "@playwright/test";

test("nested list selections retain their top-level block and paths", async ({ page }) => {
    await page.goto("/src/pages/BoardPage/components/card/comment/commentAnchor.fixture.html");
    const captured = await page.evaluate(async () => {
        const source = "/src/pages/BoardPage/components/card/comment/commentAnchor.ts";
        const { captureCardCommentAnchor } = await import(source);
        document.body.innerHTML = [
            "<div data-slate-node='element'><div id='editor'>",
            "<p data-slate-node='element'>Introduction </p><ul data-slate-node='element'>",
            "<li data-slate-node='element'><p data-slate-node='element'>First item </p></li>",
            "<li data-slate-node='element'><p data-slate-node='element' id='target'>Selected task</p></li></ul>",
            "<p data-slate-node='element'>Next block</p></div></div>",
        ].join("");
        const root = document.getElementById("editor")!;
        const range = document.createRange();
        range.selectNodeContents(document.getElementById("target")!);
        const selection = window.getSelection()!;
        selection.removeAllRanges();
        selection.addRange(range);
        return captureCardCommentAnchor(root, selection);
    });
    expect(captured?.exact).toBe("Selected task");
    expect(captured?.start_block).toBe("First item Selected task");
    expect(captured?.start_path).toEqual([1]);
    expect(captured?.end_path).toEqual([1]);
});
