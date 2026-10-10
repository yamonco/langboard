import { createRoot } from "react-dom/client";
import { useState } from "react";
import { createPlateEditor, Plate } from "platejs/react";
import { createSlateEditor } from "platejs";
import { PlateStatic } from "platejs/static";
import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";
import { yTextToSlateElement } from "@slate-yjs/core";
import { YjsPlugin } from "@platejs/yjs/react";
import { MarkdownPlugin } from "@platejs/markdown";
import { SecretReferenceKit, BaseSecretReferenceKit } from "@/components/Editor/plugins/secret-reference-kit";
import { BasicBlocksKit } from "@/components/Editor/plugins/basic-blocks-kit";
import { BaseBasicBlocksKit } from "@/components/Editor/plugins/basic-blocks-base-kit";
import { LinkKit } from "@/components/Editor/plugins/link-kit";
import { BaseLinkKit } from "@/components/Editor/plugins/link-base-kit";
import { MarkdownKit } from "@/components/Editor/plugins/markdown-kit";
import { Editor } from "./editor";
import "@/i18n";
import "@/assets/styles/main.css";

const source =
    "Reference: [legacy-caption](secret://ref/fixture) and [another-caption](secret://ref/other). " +
    "External: [External](https://example.invalid). Invalid: [Invalid](secret://ref/fixture?query=1).";
function Fixture() {
    const [saved, setSaved] = useState("");
    const [syncResult, setSyncResult] = useState("");
    const [editor] = useState(() =>
        createPlateEditor({
            plugins: [...BasicBlocksKit, ...LinkKit, ...SecretReferenceKit, ...MarkdownKit],
            value: (editor) => editor.getApi(MarkdownPlugin).markdown.deserialize(source),
        })
    );
    const [staticEditor] = useState(() =>
        createSlateEditor({
            plugins: [...BaseBasicBlocksKit, ...BaseLinkKit, ...BaseSecretReferenceKit, ...MarkdownKit],
            value: (editor) => editor.getApi(MarkdownPlugin).markdown.deserialize(source),
        })
    );
    return (
        <main className="p-5">
            <section aria-label="Masked editable">
                <Plate editor={editor}>
                    <Editor variant="none" />
                </Plate>
            </section>
            <section aria-label="Masked static">
                <PlateStatic editor={staticEditor} />
            </section>
            <button
                className="btn btn-sm"
                onClick={() => {
                    editor.tf.setValue([
                        {
                            type: "p",
                            children: [
                                { text: "JSON " },
                                { type: "a", url: "secret://ref/fixture", children: [{ text: "json-caption" }] },
                                { text: " and " },
                                { type: "secretReference", uri: "secret://ref/other", children: [{ text: "tainted-caption" }] },
                                { text: "" },
                            ],
                        },
                    ]);
                }}
            >
                Load collaborative reference
            </button>
            <button className="btn btn-sm" onClick={() => setSaved(editor.getApi(MarkdownPlugin).markdown.serialize())}>
                Save reference draft
            </button>
            <button
                className="btn btn-sm"
                disabled={!saved}
                onClick={() => editor.tf.setValue(editor.getApi(MarkdownPlugin).markdown.deserialize(saved))}
            >
                Reload reference draft
            </button>
            <button
                className="btn btn-sm"
                onClick={async () => {
                    const docs = [new Y.Doc(), new Y.Doc()];
                    const awareness = docs.map((doc) => new Awareness(doc));
                    const editors = docs.map((ydoc, index) =>
                        createPlateEditor({
                            plugins: [
                                ...BasicBlocksKit,
                                ...LinkKit,
                                ...SecretReferenceKit,
                                YjsPlugin.configure({
                                    options: {
                                        ydoc,
                                        awareness: awareness[index],
                                        cursors: null,
                                        providers: [
                                            {
                                                type: "fixture",
                                                document: ydoc,
                                                awareness: awareness[index],
                                                connect() {},
                                                disconnect() {},
                                                destroy() {},
                                                isConnected: true,
                                                isSynced: true,
                                            },
                                        ],
                                    },
                                }),
                            ],
                        })
                    );
                    const value = [
                        {
                            type: "p",
                            children: [
                                { text: "remote " },
                                { type: "a", url: "secret://ref/fixture", children: [{ text: "remote-caption" }] },
                                { text: "" },
                            ],
                        },
                    ];
                    const settle = () => new Promise<void>((resolve) => queueMicrotask(resolve));
                    try {
                        await editors[0].getApi(YjsPlugin).yjs.init({ autoConnect: false, value });
                        await settle();
                        Y.applyUpdate(docs[1], Y.encodeStateAsUpdate(docs[0]));
                        await editors[1].getApi(YjsPlugin).yjs.init({ autoConnect: false, value: null });
                        const initial = editors.map((peer) => peer.children);
                        editors[1].tf.setValue([
                            {
                                type: "p",
                                children: [
                                    { text: "updated " },
                                    { type: "secretReference", uri: "secret://ref/other", children: [{ text: "remote-tainted", bold: true }] },
                                    { text: "" },
                                ],
                            },
                        ]);
                        await settle();
                        Y.applyUpdate(docs[0], Y.encodeStateAsUpdate(docs[1]));
                        await settle();
                        Y.applyUpdate(docs[1], Y.encodeStateAsUpdate(docs[0]));
                        await settle();
                        setSyncResult(
                            JSON.stringify({
                                initial,
                                peers: editors.map((peer) => peer.children),
                                shared: docs.map((doc) => yTextToSlateElement(doc.get("content", Y.XmlText)).children),
                            })
                        );
                    } catch (error) {
                        setSyncResult(String(error));
                    } finally {
                        editors.forEach((peer) => {
                            peer.getApi(YjsPlugin).yjs.destroy();
                            peer.getOptions(YjsPlugin).awareness?.destroy();
                        });
                        docs.forEach((doc) => doc.destroy());
                    }
                }}
            >
                Verify Yjs peers
            </button>
            <pre data-sync-result>{syncResult}</pre>
            <pre data-saved-reference>{saved}</pre>
            <pre data-reference-value>{JSON.stringify(editor.children)}</pre>
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
