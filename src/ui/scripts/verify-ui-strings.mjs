import assert from "node:assert/strict";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const attributes = new Set(["aria-label", "title", "alt", "placeholder"]);
const keyTitleComponents = new Set(["BoardSettingsSection", "BoardCardSection", "BoardBotScopeItemDialog"]);
const humanText = (text) => /\p{L}/u.test(text.replace(/&(?:[a-z]+|#\d+|#x[0-9a-f]+);/gi, ""));

/** Only source literals are candidates; user/model content and translated expressions are never rewritten. */
export function scanSource(file, source) {
    const tree = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const findings = [];
    function add(node, kind, text) {
        text = text.replace(/\s+/g, " ").trim();
        if (!humanText(text)) return;
        findings.push({ file, line: tree.getLineAndCharacterOfPosition(node.getStart(tree)).line + 1, kind, text });
    }
    function visit(node) {
        if (ts.isJsxText(node)) add(node, "jsx-text", node.text);
        if (ts.isJsxExpression(node) && !ts.isJsxAttribute(node.parent) && node.expression && ts.isStringLiteralLike(node.expression)) {
            add(node, "jsx-expression", node.expression.text);
        }
        if (ts.isJsxAttribute(node) && attributes.has(node.name.getText(tree)) && node.initializer) {
            const literal = ts.isStringLiteral(node.initializer)
                ? node.initializer
                : ts.isJsxExpression(node.initializer) && node.initializer.expression && ts.isStringLiteralLike(node.initializer.expression)
                  ? node.initializer.expression
                  : null;
            if (literal) {
                const name = node.name.getText(tree);
                const tag = node.parent.parent.tagName.getText(tree);
                // These components translate namespace-qualified title keys internally.
                if (!(name === "title" && keyTitleComponents.has(tag) && /^[a-zA-Z]+\./.test(literal.text))) {
                    add(node, `attribute:${name}`, literal.text);
                }
            }
        }
        if (ts.isCallExpression(node)) {
            const callee = node.expression.getText(tree);
            const kind =
                /(?:^|\.)(?:confirm|alert|prompt)$/.test(callee) || /Toast\.Add\.(?:error|success|warning|info)$/.test(callee)
                    ? "dialog-toast"
                    : /(?:^|\.)(?:min|max|email|regex|nonempty|refine)$/.test(callee)
                      ? "validation"
                      : null;
            if (kind)
                for (const arg of node.arguments) {
                    if (ts.isStringLiteralLike(arg)) add(arg, kind, arg.text);
                    if (ts.isObjectLiteralExpression(arg))
                        for (const prop of arg.properties) {
                            if (ts.isPropertyAssignment(prop) && prop.name.getText(tree) === "message" && ts.isStringLiteralLike(prop.initializer))
                                add(prop, kind, prop.initializer.text);
                        }
                }
        }
        ts.forEachChild(node, visit);
    }
    visit(tree);
    return findings;
}

const identity = (item) => JSON.stringify([item.file, item.kind, item.text]);
export function regressions(current, baseline) {
    const remaining = new Map();
    for (const item of baseline) remaining.set(identity(item), (remaining.get(identity(item)) ?? 0) + 1);
    return current.filter((item) => {
        const key = identity(item),
            count = remaining.get(key) ?? 0;
        if (count) {
            remaining.set(key, count - 1);
            return false;
        }
        return true;
    });
}
function files(dir) {
    return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
        const path = join(dir, entry.name);
        if (entry.isDirectory()) return files(path);
        return /\.tsx?$/.test(entry.name) && !/\.(?:fixture|test|spec)\./.test(entry.name) && !entry.name.endsWith(".d.ts") ? [path] : [];
    });
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
    const findings = files(join(root, "src")).flatMap((path) => scanSource(relative(root, path), readFileSync(path, "utf8")));
    const baselinePath = join(root, "scripts/ui-strings-baseline.json");
    if (process.argv.includes("--write-baseline")) {
        writeFileSync(baselinePath, JSON.stringify(findings, null, 2) + "\n");
    } else if (process.argv.includes("--inventory")) {
        process.stdout.write(JSON.stringify(findings, null, 2) + "\n");
    } else {
        const introduced = regressions(findings, JSON.parse(readFileSync(baselinePath, "utf8")));
        assert.equal(introduced.length, 0, `New untranslated UI literals:\n${JSON.stringify(introduced, null, 2)}`);
        console.log(JSON.stringify({ existingCandidates: findings.length, newCandidates: introduced.length }));
    }
}
