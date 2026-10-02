import { createRoot } from "react-dom/client";
import { useRef } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { ProjectColumn } from "@/core/models";
import BoardColumnName, { BoardColumnNameInput } from "./BoardColumnName";
import BoardColumnDescription from "./BoardColumnDescription";
import i18n from "@/i18n";
import "@/assets/styles/main.css";
const fields = {
    name: "Queue",
    description: "Waiting for work",
    workflow_stage: null,
    is_archive: false,
    translations: {
        en: { name: "Old English", description: "Old English description" },
        ko: { name: "대기", description: "작업 대기" },
        ja: { name: "待機", description: "作業待ち" },
        zh: { name: "队列", description: "等待工作" },
    },
};
const column = {
    ...fields,
    uid: "column",
    project_uid: "board",
    useField: (key: keyof typeof fields) => fields[key],
} as unknown as ProjectColumn.TModel;
function Fixture() {
    const ref = useRef<HTMLInputElement>(null);
    return (
        <main className="max-w-sm p-4">
            <BoardColumnName isDragging={false} column={column} />
            <BoardColumnDescription column={column} />
            <div data-testid="canonical-editor">
                <BoardColumnNameInput isEditing={true} columnName={fields.name} inputRef={ref} changeMode={() => {}} />
            </div>
            <output>{JSON.stringify({ name: column.name, description: column.description, workflow_stage: column.workflow_stage })}</output>
        </main>
    );
}
await i18n.changeLanguage(new URLSearchParams(location.search).get("lang") ?? "en-US");
createRoot(document.getElementById("root")!).render(
    <MemoryRouter>
        <QueryClientProvider client={new QueryClient()}>
            <Fixture />
        </QueryClientProvider>
    </MemoryRouter>
);
