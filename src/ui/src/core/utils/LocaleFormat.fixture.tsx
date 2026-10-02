import { createPlateEditor, Plate } from "platejs/react";
import { CodeBlockKit } from "@/components/Editor/plugins/code-block-kit";
import { Editor } from "@/components/plate-ui/editor";
import CardContentBlockList from "@/pages/BoardPage/components/card/CardContentBlockList";
import RelationshipTypePicker from "@/pages/BoardPage/components/board/RelationshipTypePicker";
import { GlobalRelationshipType } from "@/core/models";
import BoardWorkIsland from "@/pages/BoardPage/components/board/BoardWorkIsland";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { Project } from "@/core/models";
import { api } from "@/core/helpers/Api";
import { useState } from "react";
import Breadcrumb from "@/components/base/Breadcrumb";
import Dialog from "@/components/base/Dialog";
import MarkdownThinkBlock from "@/components/Markdown/ThinkBlock";
import Calendar from "@/components/base/Calendar";
import { createRoot } from "react-dom/client";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import "@/core/injection/StringExtensions";
import useUpdateDateDistance from "@/core/hooks/useUpdateDateDistance";
import { formatDateTime, formatTimerDuration, formatNumber } from "./LocaleFormat";
import { SUPPORTED_LOCALES } from "./LocalePolicy";

api.defaults.adapter = async (config) => ({ status: 200, statusText: "OK", headers: {}, config, data: { active_work: [] } });
const fixtureProject = { uid: "locale-fixture" } as Project.TModel;
const fixtureRelationships = ["contains", "blocks", "references"].map((machine_semantic) => ({
    uid: machine_semantic,
    machine_semantic,
    is_active: true,
    parent_name: `User ${machine_semantic}`,
    child_name: `User ${machine_semantic}`,
})) as GlobalRelationshipType.TModel[];
const date = new Date(Date.now() - 300000);
function Fixture() {
    const [t, language] = useTranslation();
    const [dragging, setDragging] = useState(false);
    const [editor] = useState(() =>
        createPlateEditor({
            plugins: [...CodeBlockKit],
            value: [{ type: "code_block", lang: "plaintext", children: [{ type: "code_line", children: [{ text: "const user = 1;" }] }] }],
        })
    );
    const distance = useUpdateDateDistance(date);
    return (
        <>
            <div data-testid="code-editor">
                <Plate editor={editor}>
                    <Editor aria-label="fixture code editor" />
                </Plate>
            </div>
            <div data-testid="content-blocks">
                <CardContentBlockList
                    blocks={[
                        {
                            block_uid: "source",
                            revision: 0,
                            updated_at: null,
                            order: 0,
                            type: "diagram",
                            payload: { engine: "mermaid", source: "graph TD; User--&gt;Data;", view_mode: "source" },
                        },
                        {
                            block_uid: "empty",
                            revision: 0,
                            updated_at: null,
                            order: 1,
                            type: "diagram",
                            payload: { engine: "mermaid", source: "", view_mode: "image" },
                        },
                    ]}
                />
            </div>
            <div data-testid="relationship-picker">
                <RelationshipTypePicker types={fixtureRelationships} isParent onSelect={() => {}} />
            </div>
            <div data-testid="work-island">
                <BoardWorkIsland project={fixtureProject} dragging={dragging} />
            </div>
            <input type="checkbox" aria-label="fixture dragging" checked={dragging} onChange={(event) => setDragging(event.target.checked)} />
            <div data-testid="common-ui">
                <Breadcrumb.Root>
                    <Breadcrumb.List>
                        <Breadcrumb.Item>
                            <Breadcrumb.Ellipsis />
                        </Breadcrumb.Item>
                    </Breadcrumb.List>
                </Breadcrumb.Root>
                <Dialog.Root>
                    <Dialog.CloseButton />
                </Dialog.Root>
                <MarkdownThinkBlock>Fixture content</MarkdownThinkBlock>
            </div>
            <output data-testid="relative">{distance}</output>
            <output data-testid="overdue-one">{t("card.Overdue by {{count}} day", { count: 1 })}</output>
            <output data-testid="overdue-other">{t("card.Overdue by {{count}} day", { count: 2 })}</output>
            <output data-testid="duration">{formatTimerDuration({ hours: 1, minutes: 2, seconds: 3 }, language.language)}</output>
            <output data-testid="count">{formatNumber(12345, language.language)}</output>
            <div data-testid="calendar">
                <Calendar value={new Date(2026, 9, 3, 13)} onChange={() => {}} hideTime />
            </div>
            <output data-testid="exact">{formatDateTime(date, language.language)}</output>
            {SUPPORTED_LOCALES.map((locale) => (
                <button key={locale} onClick={() => void language.changeLanguage(locale)}>
                    {locale}
                </button>
            ))}
        </>
    );
}
function render() {
    createRoot(document.getElementById("root")!).render(
        <QueryClientProvider client={new QueryClient()}>
            <MemoryRouter>
                <Fixture />
            </MemoryRouter>
        </QueryClientProvider>
    );
}
if (i18n.isInitialized) render();
else i18n.on("initialized", render);
