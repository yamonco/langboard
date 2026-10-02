import assert from "node:assert/strict";
import { test } from "node:test";
import { regressions, scanSource } from "./verify-ui-strings.mjs";

test("raw accessible text, dialog and validation literals are detected; translated and user content are excluded", () => {
    const found = scanSource(
        "Example.tsx",
        `
        const view = <><button aria-label="Open menu">Open</button><input placeholder={"Name"}/><span>{user.title}</span><span>{t("common.Close")}</span><BoardCardSection title="card.Description"/></>;
        window.confirm("Delete this item?"); Toast.Add.error("Save failed"); z.string().min(1, { message: "Required" });
    `
    );
    assert.deepEqual(
        found.map((x) => [x.kind, x.text]),
        [
            ["attribute:aria-label", "Open menu"],
            ["jsx-text", "Open"],
            ["attribute:placeholder", "Name"],
                ["dialog-toast", "Delete this item?"],
            ["dialog-toast", "Save failed"],
            ["validation", "Required"],
        ]
    );
    assert.equal(regressions(found, []).length, 6);
    assert.equal(regressions(found, found).length, 0);
    assert.equal(regressions([...found, found[0]], found).length, 1);
    assert.equal(regressions(found, found.slice(1)).length, 1);
    assert.equal(regressions(scanSource("Example.tsx", '<button aria-label={t("common.Open")}>{user.title}</button>'), found).length, 0);
});

test("TypeScript generics and HTML spacing entities are not user-facing messages", () => {
    assert.deepEqual(scanSource("Models.ts", "const identity = <T>(value: T): T => value;"), []);
    assert.deepEqual(scanSource("Spacing.tsx", "const view = <span>&nbsp;</span>;"), []);
});
