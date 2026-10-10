import { useState } from "react";
import { createRoot } from "react-dom/client";
import { createPlateEditor, Plate } from "platejs/react";
import { MemoryRouter } from "react-router";
import { DndProvider } from "react-dnd";
import { HTML5Backend } from "react-dnd-html5-backend";
import { TableKit } from "./plugins/table-kit";
import { Editor } from "@/components/plate-ui/editor";
import "@/assets/styles/main.css";

function Fixture() {
    const [editor] = useState(() =>
        createPlateEditor({
            plugins: TableKit,
            value: [
                {
                    type: "table",
                    children: [
                        {
                            type: "tr",
                            children: ["Alpha", "Bravo"].map((text) => ({
                                type: "td",
                                children: [{ type: "p", children: [{ text }] }],
                            })),
                        },
                    ],
                },
            ],
        })
    );
    const select = (multiple: boolean) => {
        editor.tf.select({ anchor: { path: [0, 0, 0, 0, 0], offset: 0 }, focus: { path: [0, 0, multiple ? 1 : 0, 0, 0], offset: 5 } });
        editor.tf.focus();
    };
    return (
        <main style={{ padding: 100 }}>
            <button onMouseDown={(event) => event.preventDefault()} onClick={() => select(false)}>
                Select single cell text
            </button>
            <button onMouseDown={(event) => event.preventDefault()} onClick={() => select(true)}>
                Select multiple cells
            </button>
            <Plate editor={editor}>
                <Editor aria-label="Table content" />
            </Plate>
        </main>
    );
}
createRoot(document.getElementById("root")!).render(
    <MemoryRouter>
        <DndProvider backend={HTML5Backend}>
            <Fixture />
        </DndProvider>
    </MemoryRouter>
);
