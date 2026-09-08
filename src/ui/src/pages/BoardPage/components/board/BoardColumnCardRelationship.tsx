import Button from "@/components/base/Button";
import { ProjectCardRelationship } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardController } from "@/core/providers/BoardController";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { IBoardColumnCardContextParams } from "@/pages/BoardPage/components/board/BoardConstants";
import { memo } from "react";
import { useTranslation } from "react-i18next";
import { useBoard } from "@/core/providers/BoardProvider";

export interface IBoardColumnCardRelationshipProps {
    attributes: Record<string, unknown>;
}

const BoardColumnCardRelationship = memo(({ attributes }: IBoardColumnCardRelationshipProps) => {
    return (
        <>
            <BoardColumnCardRelationshipButton type="parents" attributes={attributes} />
            <BoardColumnCardRelationshipButton type="children" attributes={attributes} />
        </>
    );
});
BoardColumnCardRelationship.displayName = "Board.ColumnCardRelationship";

export interface IBoardColumnCardRelationshipButtonProps {
    type: ProjectCardRelationship.TRelationship;
    attributes: Record<string, unknown>;
}

const BoardColumnCardRelationshipButton = memo(({ type, attributes }: IBoardColumnCardRelationshipButtonProps) => {
    const [t] = useTranslation();
    const { model: card, params } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const { setFilters } = params;
    const isParent = type === "parents";
    const { filterRelationships } = useBoardController();
    const { cardsMap } = useBoard();
    const flatRelationships = card.useForeignFieldArray("relationships");
    const relationships = filterRelationships(card.uid, flatRelationships, isParent).filter((relationship) => {
        const relatedCardUID = isParent ? relationship.parent_card_uid : relationship.child_card_uid;
        return cardsMap[relatedCardUID]?.project_column_uid !== card.project_column_uid;
    });

    if (!relationships.length) {
        return null;
    }

    const relationshipCount = relationships.length > 99 ? "99" : relationships.length;

    return (
        <Button
            size="icon-sm"
            className={cn(
                "absolute top-1/2 z-30 block -translate-y-1/2 transform rounded-full text-xs hover:bg-primary/70",
                isParent ? "-left-3" : "-right-3"
            )}
            title={t(`project.${new Utils.String.Case(type).toPascal()}`)}
            titleSide={isParent ? "right" : "left"}
            onClick={() => setFilters(type)}
            {...attributes}
        >
            +{relationshipCount}
        </Button>
    );
});
BoardColumnCardRelationshipButton.displayName = "Board.ColumnCardRelationshipButton";

export default BoardColumnCardRelationship;
