import { DescriptionOverviewRail } from "@/pages/BoardPage/components/card/description/DescriptionOverviewRail";
import DataTablePagination from "@/components/base/DataTable/Pagination";
import { DataTableProvider } from "@/components/base/DataTable/Provider";
import { createPlateEditor, Plate } from "platejs/react";
import { CodeBlockKit } from "@/components/Editor/plugins/code-block-kit";
import { Editor } from "@/components/plate-ui/editor";
import CardContentBlockList from "@/pages/BoardPage/components/card/CardContentBlockList";
import RelationshipTypePicker from "@/pages/BoardPage/components/board/RelationshipTypePicker";
import { GlobalRelationshipType } from "@/core/models";
import BoardWorkIsland from "@/pages/BoardPage/components/board/BoardWorkIsland";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { Project, ProjectCard } from "@/core/models";
import BoardOutlineSidebar from "@/pages/BoardPage/components/board/BoardOutlineSidebar";
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
const railChunks = Array.from({ length: 1234 }, (_, index) => ({
    id: `rail-${index}`,
    content: `User block ${index}`,
    metadata: { type: "paragraph" as const, previewText: `User block ${index}`, textLength: 12, isHeavy: false },
}));
ProjectCard.Model.fromOne({
    uid: "locale-outline",
    project_uid: "locale-fixture",
    project_column_uid: "locale-column",
    title: "User card title",
    description: "",
    order: 0,
    created_at: new Date(),
    updated_at: new Date(),
    checklist_total_count: 2345,
    checklist_completed_count: 1234,
    count_comment: 1234,
    relationships: [],
});
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
            <div data-testid="outline-counts">
                <BoardOutlineSidebar cardUID="locale-outline" onRelations={() => {}} />
            </div>
            <div data-testid="pagination-counts">
                <DataTableProvider totalRecords={2345} itemsPerPage={1234}>
                    <DataTablePagination />
                </DataTableProvider>
            </div>
            <output data-testid="numeric-notification">{t("notification.{count} notifications received", { count: 1234 })}</output>
            <output data-testid="numeric-activity">{t("activity.{count} New Activities", { count: 1234 })}</output>
            <output data-testid="numeric-approval">{t("bot.{count} pending approvals", { count: 1234 })}</output>
            <div data-testid="description-rail" className="relative h-96">
                <DescriptionOverviewRail chunks={railChunks} activeIndex={1233} onNavigate={() => {}} />
            </div>
            <output data-testid="relative">{distance}</output>
            <output data-testid="remaining-counts">
                {[
                    "settings.Partial Admin ({{count}} permissions)",
                    "settings.Partial access ({{count}} permissions)",
                    "settings.Selected event count",
                    "dashboard.Showing recent work",
                    "card.Seen by count",
                    "mcp.Available Tools ({count})",
                    "mcp.{count} tools",
                ].map((key) => (
                    <span key={key} data-count-key={key}>
                        {t(key, { count: 1234 })}
                    </span>
                ))}
            </output>
            <output data-testid="workflow-stage-label">{t("board.Workflow stage display", { stage: "User stage" })}</output>
            <output data-testid="graph-counts">
                {t("board.{cards} cards, {relationships} relationships", { cards: 1234, relationships: 2345 })}
            </output>
            <output data-testid="checklist-counts">{t("card.Checklist progress", { completed: 1234, total: 2345 })}</output>
            <output data-testid="stale-one">{t("card.Unchanged for {{days}} days", { days: 1, count: 1 })}</output>
            <output data-testid="stale-many">{t("card.Unchanged for {{days}} days", { days: 1234, count: 1234 })}</output>
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
