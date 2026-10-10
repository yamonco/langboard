import { useTranslation } from "react-i18next";
import { GlobalRelationshipType, ProjectCard } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";

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
    const parents = relationships.filter((relationship) => relationship.child_card_uid === card.uid);
    const children = relationships.filter((relationship) => relationship.parent_card_uid === card.uid);

    return (
        <div className="space-y-3 text-sm">
            <p className="truncate px-2 font-medium" title={card.title}>
                {card.title}
            </p>
            {(
                [
                    [t("dashboard.Parents"), parents, true],
                    [t("dashboard.Children"), children, false],
                ] as const
            ).map(([label, items, isParent]) => (
                <section key={label}>
                    <h2 className="px-2 py-1 text-xs font-medium text-muted-foreground">
                        {label} · {items.length}
                    </h2>
                    {items.map((relationship) => {
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
