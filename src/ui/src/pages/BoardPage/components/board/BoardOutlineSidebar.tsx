import { useTranslation } from "react-i18next";
import { ProjectCard, ProjectCardAttachment } from "@/core/models";
import { WORKBENCH_OUTLINE_EVENT } from "@/pages/DashboardPage/components/WorkbenchCommands";

type TOutlineSection = "description" | "checklists" | "comments" | "attachments";

export default function BoardOutlineSidebar({ cardUID, onRelations }: { cardUID?: string; onRelations: () => void }) {
    const [t] = useTranslation();
    const card = ProjectCard.Model.useModel(cardUID ?? "", [cardUID]);

    return (
        <nav aria-label={t("dashboard.Outline")} data-workbench-context="" className="flex h-full min-w-0 flex-col overflow-hidden">
            <div className="shrink-0 border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide">{t("dashboard.Outline")}</div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {card ? (
                    <CardOutline card={card} onRelations={onRelations} />
                ) : (
                    <p className="px-2 py-3 text-sm text-muted-foreground">{t("dashboard.Open a card to see its context")}</p>
                )}
            </div>
        </nav>
    );
}

function CardOutline({ card, onRelations }: { card: ProjectCard.TModel; onRelations: () => void }) {
    const [t] = useTranslation();
    const checklistTotal = card.useField("checklist_total_count") ?? 0;
    const checklistCompleted = card.useField("checklist_completed_count") ?? 0;
    const commentCount = card.useField("count_comment") ?? 0;
    const hasDescription = card.useField("has_description") ?? false;
    const contentBlocks = card.useField("content_blocks") ?? [];
    const relationships = card.useForeignFieldArray("relationships");
    const attachments = ProjectCardAttachment.Model.useModels((attachment) => attachment.card_uid === card.uid, [card.uid]);
    const sections: Array<{ key: TOutlineSection; label: string; count?: string }> = [
        ...(hasDescription ? [{ key: "description" as const, label: t("card.Description") }] : []),
        ...(checklistTotal ? [{ key: "checklists" as const, label: t("card.Checklists"), count: `${checklistCompleted}/${checklistTotal}` }] : []),
        { key: "comments", label: t("card.Comments"), count: String(commentCount) },
        ...(attachments.length ? [{ key: "attachments" as const, label: t("card.Attached files"), count: String(attachments.length) }] : []),
    ];
    const openSection = (section: TOutlineSection, blockUID?: string) =>
        window.dispatchEvent(new CustomEvent(WORKBENCH_OUTLINE_EVENT, { detail: { cardUID: card.uid, section, blockUID } }));

    return (
        <div className="space-y-1 text-sm">
            <p className="truncate px-2 py-1 font-medium" title={card.title}>
                {card.title}
            </p>
            {sections.map((section) => (
                <button
                    key={section.key}
                    type="button"
                    className="flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-muted"
                    onClick={() => openSection(section.key)}
                >
                    <span className="min-w-0 flex-1 truncate">{section.label}</span>
                    {section.count && <span className="text-xs text-muted-foreground">{section.count}</span>}
                </button>
            ))}
            <button type="button" className="flex w-full items-center gap-2 rounded px-2 py-1 text-left hover:bg-muted" onClick={onRelations}>
                <span className="min-w-0 flex-1 truncate">{t("dashboard.Relations")}</span>
                <span className="text-xs text-muted-foreground">{relationships.length}</span>
            </button>
            {[...contentBlocks]
                .sort((a, b) => a.order - b.order)
                .filter((block) => block.type === "code" || block.type === "diagram")
                .map((block, index) => (
                    <button
                        key={block.block_uid}
                        type="button"
                        className="block w-full truncate rounded px-4 py-1 text-left text-xs text-muted-foreground hover:bg-muted"
                        onClick={() => openSection("description", block.block_uid)}
                    >
                        {t(block.type === "code" ? "dashboard.Code blocks" : "dashboard.Diagrams")} {index + 1}
                    </button>
                ))}
        </div>
    );
}
