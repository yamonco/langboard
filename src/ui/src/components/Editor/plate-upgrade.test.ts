import assert from "node:assert/strict";
import test from "node:test";
import { createRequire } from "node:module";
import { createPlateEditor } from "platejs/react";
import { YjsPlugin } from "@platejs/yjs/react";
import { createSlateEditor } from "platejs";
import { BaseBlockquotePlugin, BaseBoldPlugin, BaseH1Plugin, BoldRules, HeadingRules } from "@platejs/basic-nodes";
import { MarkdownPlugin } from "@platejs/markdown";

test("resetting an editor clears the shared document rather than only its visible children", async () => {
    const editor = createPlateEditor({
        plugins: [
            YjsPlugin.configure({
                options: { providers: [{ type: "test", connect() {}, disconnect() {}, destroy() {}, isConnected: true, isSynced: true }] },
            }),
        ],
    });
    const api = editor.getApi(YjsPlugin).yjs;
    const doc = editor.getOptions(YjsPlugin).ydoc;
    try {
        await api.init({ autoConnect: false, value: [{ type: "p", children: [{ text: "discarded draft" }] }] });
        assert.ok(doc.get("content").toString().includes("discarded draft"));
        editor.tf.reset();
        editor.tf.setValue([{ type: "p", children: [{ text: "" }] }]);
        await new Promise<void>((resolve) => queueMicrotask(resolve));
        assert.ok(!doc.get("content").toString().includes("discarded draft"));
    } finally {
        api.destroy();
        editor.getOptions(YjsPlugin).awareness?.destroy();
        doc.destroy();
    }
});

test("native heading and bold input rules survive editor recreation", () => {
    const plugins = [
        BaseH1Plugin.configure({ inputRules: [HeadingRules.markdown()] }),
        BaseBoldPlugin.configure({ inputRules: [BoldRules.markdown({ variant: "*" })] }),
    ];
    for (let index = 0; index < 2; index++) {
        const editor = createSlateEditor({ plugins, value: [{ type: "p", children: [{ text: "" }] }] });
        editor.tf.select({ path: [0, 0], offset: 0 });
        for (const character of "# ") editor.tf.insertText(character);
        assert.equal(editor.children[0].type, "h1");
        for (const character of "**한글**") editor.tf.insertText(character);
        assert.equal(editor.children[0].children[0].text, "한글");
        assert.equal(editor.children[0].children[0].bold, true);
    }
});

test("legacy blockquotes normalize and nested quotes preserve their text through Markdown", () => {
    const editor = createSlateEditor({
        plugins: [BaseBlockquotePlugin, MarkdownPlugin],
        value: [{ type: "blockquote", children: [{ text: "기존 인용문" }] }],
    });
    editor.tf.normalize({ force: true });
    assert.equal(editor.children[0].children[0].type, "p");
    const source = "> 인용\n>\n> > 중첩";
    editor.tf.setValue(editor.api.markdown.deserialize(source));
    const saved = editor.api.markdown.serialize();
    assert.ok(saved.includes("인용"));
    assert.ok(saved.includes("> > 중첩"));
});

test("the app and Plate share one Slate React context and transform implementation", () => {
    const app = createRequire(import.meta.url);
    const plate = createRequire(app.resolve("@platejs/core"));
    for (const name of ["slate", "slate-dom", "slate-react"]) {
        assert.equal(app.resolve(name), plate.resolve(name), `${name} must resolve to one package instance`);
    }
});
