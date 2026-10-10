import { createRoot } from "react-dom/client";
import { createPlateEditor, Plate } from "platejs/react";
import { createSlateEditor } from "platejs";
import { PlateStatic } from "platejs/static";
import { BaseLinkPlugin } from "@platejs/link";
import { LinkKit } from "@/components/Editor/plugins/link-kit";
import { LinkElementStatic } from "./link-node-static";
import { Editor } from "./editor";
import "@/i18n";
import "@/assets/styles/main.css";
const value = [
    {
        type: "p",
        children: [
            { text: "Reference: " },
            { type: "a", url: "secret://ref/fixture", children: [{ text: "••••" }] },
            { text: " External: " },
            { type: "a", url: "https://example.invalid", children: [{ text: "External" }] },
            { text: " Invalid: " },
            { type: "a", url: "secret://ref/fixture?other=1", children: [{ text: "Invalid" }] },
            { text: "" },
        ],
    },
];
const editor = createPlateEditor({ plugins: LinkKit, value });
const staticEditor = createSlateEditor({ plugins: [BaseLinkPlugin.withComponent(LinkElementStatic)], value });
createRoot(document.getElementById("root")!).render(
    <main className="p-5">
        <section aria-label="Editable reference">
            <Plate editor={editor}>
                <Editor variant="none" />
            </Plate>
        </section>
        <section aria-label="Static reference">
            <PlateStatic editor={staticEditor} />
        </section>
    </main>
);
