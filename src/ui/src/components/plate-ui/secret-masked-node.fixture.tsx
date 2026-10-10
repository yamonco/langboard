import { createRoot } from "react-dom/client";
import { useState } from "react";
import { createPlateEditor, Plate } from "platejs/react";
import { createSlateEditor } from "platejs";
import { PlateStatic } from "platejs/static";
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
            <pre data-saved-reference>{saved}</pre>
            <pre data-reference-value>{JSON.stringify(editor.children)}</pre>
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Fixture />);
