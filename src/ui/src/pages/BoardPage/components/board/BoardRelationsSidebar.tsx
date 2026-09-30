import { useTranslation } from "react-i18next";
import { GlobalRelationshipType, ProjectCard } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { RELATIONSHIP_GROUPS } from "@/pages/BoardPage/components/board/RelationshipTypePicker";
import { Link2 } from "lucide-react";
import { hasContainmentCycle } from "./BoardColumnCardHierarchy";

export default function BoardRelationsSidebar({ projectUID, cardUID }: { projectUID: string; cardUID?: string }) {
    const [t] = useTranslation();
    const card = ProjectCard.Model.useModel(cardUID ?? "", [cardUID]);
    const navigate = usePageNavigateRef();

    return (
        <nav aria-label={t("dashboard.Relations")} data-workbench-context="" className="flex h-full w-full min-w-0 flex-col overflow-hidden">
            <div className="flex shrink-0 items-center justify-between border-b px-3 py-2 text-xs font-semibold uppercase tracking-wide">
                <span>{t("dashboard.Relations")}</span>
                <button type="button" className="text-primary hover:underline" onClick={() => navigate(ROUTES.BOARD.GRAPH(projectUID))}>
                    {t("dashboard.Full graph")}
                </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {card && card.project_uid === projectUID ? (
                    <RelationsTree card={card} projectUID={projectUID} />
                ) : (
                    <p className="px-2 py-3 text-sm text-muted-foreground">{t("dashboard.Open a card to see its context")}</p>
                )}
            </div>
        </nav>
    );
}

function RelationsTree({ card, projectUID }: { card: ProjectCard.TModel; projectUID: string }) {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const relationships = card.useForeignFieldArray("relationships");
    const workState = card.useField("work_state");
    const blockers = workState?.dependency_state?.direct_blockers ?? [];
    const containsCycle = hasContainmentCycle(ProjectCard.Model.getModels((candidate) => candidate.project_uid === projectUID), card.uid);
    const semanticOf = (relationship: (typeof relationships)[number]) =>
        relationship.machine_semantic ?? GlobalRelationshipType.Model.getModel(relationship.relationship_type_uid)?.machine_semantic;
    const sections = [
        ...RELATIONSHIP_GROUPS.map((group) => ({
            key: group.semantic,
            label: group.label,
            Icon: group.Icon,
            items: relationships.filter((relationship) => semanticOf(relationship) === group.semantic),
        })),
        {
            key: "legacy",
            label: "기존 미분류 관계",
            Icon: Link2,
            items: relationships.filter((relationship) => !semanticOf(relationship)),
        },
    ].filter((group) => group.items.length);

    return (
        <div className="space-y-3 text-sm">
            <p className="truncate px-2 font-medium" title={card.title}>
                {card.title}
            </p>
            {containsCycle && (
                <p role="status" className="px-2 text-xs text-muted-foreground">
                    포함 관계 순환이 있습니다. 트리 표시를 제한하며 실행을 차단하지 않습니다.
                </p>
            )}
            {blockers.length > 0 && (
                <section aria-label="막힌 이유">
                    <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">막힌 이유 · {blockers.length}</h2>
                    {blockers.map((blocker) =>
                        blocker.accessible && blocker.card_uid ? (
                            <button
                                key={blocker.relationship_uid}
                                type="button"
                                className="block w-full truncate rounded px-2 py-1 text-left hover:bg-muted"
                                onClick={() => navigate(ROUTES.BOARD.CARD(projectUID, blocker.card_uid!))}
                            >
                                {blocker.title}
                            </button>
                        ) : (
                            <p key={blocker.relationship_uid} className="px-2 py-1 text-muted-foreground">
                                접근할 수 없는 선행조건
                            </p>
                        )
                    )}
                </section>
            )}
            {sections.map(({ key, label, Icon, items }) => (
                <section key={key}>
                    <h2 className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-muted-foreground">
                        <Icon size={14} aria-hidden="true" /> {label} · {items.length}
                    </h2>
                    {items.map((relationship) => {
                        const isParent = relationship.child_card_uid === card.uid;
                        const targetUID = isParent ? relationship.parent_card_uid : relationship.child_card_uid;
                        const target = ProjectCard.Model.getModel(targetUID);
                        if (!target || target.project_uid !== projectUID) return null;
                        const type = GlobalRelationshipType.Model.getModel(relationship.relationship_type_uid);
                        const relationName = isParent ? type?.parent_name : type?.child_name;
                        return (
                            <button
                                key={relationship.uid}
                                type="button"
                                className="flex w-full min-w-0 flex-col rounded px-2 py-1 text-left hover:bg-muted"
                                onClick={() => navigate(ROUTES.BOARD.CARD(projectUID, targetUID))}
                            >
                                <span className="truncate">{target.title}</span>
                                {relationName && <span className="truncate text-xs text-muted-foreground">{relationName}</span>}
                            </button>
                        );
                    })}
                </section>
            ))}
            {!relationships.length && <p className="px-2 text-muted-foreground">{t("dashboard.No relationships")}</p>}
        </div>
    );
}
