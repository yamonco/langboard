import { createRoot } from "react-dom/client";
import { useState } from "react";
import { createPlateEditor, Plate } from "platejs/react";
import { MarkdownPlugin } from "@platejs/markdown";
import { BasicBlocksKit } from "../basic-blocks-kit";
import { ListKit } from "../list-kit";
import { MarkdownKit } from "../markdown-kit";
import { AutoformatKit } from "../autoformat-kit";
import { Editor } from "@/components/plate-ui/editor";
import "@/assets/styles/main.css";

const initial = "1. One\n9. Nine\n2. Two\n1. Again\n2. Later";

function Fixture() {
    const [saved, setSaved] = useState("");
    const [readOnly, setReadOnly] = useState(true);
    const [editor] = useState(() =>
        createPlateEditor({
            plugins: [...BasicBlocksKit, ...ListKit, ...MarkdownKit, ...AutoformatKit],
            value: (editor) => editor.getApi(MarkdownPlugin).markdown.deserialize(initial),
        })
    );
    return (
        <main style={{ padding: 24, maxWidth: 700, margin: "auto" }}>
            <h1>Numbered editor</h1>
            <div className="min-w-0 overflow-hidden rounded border p-3" data-number-card>
                <Plate editor={editor} readOnly={readOnly}>
                    <Editor variant="ai" aria-label="Numbered content" />
                </Plate>
            </div>
            <button onClick={() => setReadOnly(!readOnly)}>{readOnly ? "Edit draft" : "Read draft"}</button>
            <button onClick={() => setSaved(editor.getApi(MarkdownPlugin).markdown.serialize())}>Save draft</button>
            <button disabled={!saved} onClick={() => editor.tf.setValue(editor.getApi(MarkdownPlugin).markdown.deserialize(saved))}>
                Reload draft
            </button>
            <pre data-saved-draft>{saved}</pre>
        </main>
    );
}

createRoot(document.getElementById("root")!).render(<Fixture />);
