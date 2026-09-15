import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

test("failed deletion leaves the card model intact; only success removes it", () => {
    const source = ts.createSourceFile(
        "BoardCardActionDelete.tsx",
        readFileSync(new URL("./BoardCardActionDelete.tsx", import.meta.url), "utf8"),
        ts.ScriptTarget.Latest,
        true,
        ts.ScriptKind.TSX
    );
    const callbacks = new Map<string, ts.ArrowFunction>();
    const visit = (node: ts.Node) => {
        if (ts.isPropertyAssignment(node) && ts.isArrowFunction(node.initializer)) {
            callbacks.set(node.name.getText(source), node.initializer);
        }
        ts.forEachChild(node, visit);
    };
    visit(source);
    const countRemovals = (node: ts.Node): number => {
        let count = ts.isCallExpression(node) && node.expression.getText(source) === "deleteCardModel" ? 1 : 0;
        ts.forEachChild(node, (child) => {
            count += countRemovals(child);
        });
        return count;
    };
    assert.equal(countRemovals(callbacks.get("success")!), 1);
    assert.equal(countRemovals(callbacks.get("error")!), 0);
    assert.equal(countRemovals(callbacks.get("finally")!), 0);
});

test("deletion denial has actionable localized copy, not an internal error key", () => {
    const errors = JSON.parse(readFileSync(new URL("../../../../../assets/locales/en-US/errors.json", import.meta.url), "utf8"));
    assert.equal(errors.requests.PE2006, "Only the original author or an administrator can delete this card. The card has not been deleted.");
});
