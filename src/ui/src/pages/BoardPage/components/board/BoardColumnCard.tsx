"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import invariant from "tiny-invariant";
import { BOARD_CARD_TOUCH_DND_ATTR, BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { ProjectCard, ProjectCardRelationship } from "@/core/models";
import Box from "@/components/base/Box";
import Card from "@/components/base/Card";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardController } from "@/core/providers/BoardController";
import { useBoard } from "@/core/providers/BoardProvider";
import BoardColumnCardCollapsible from "@/pages/BoardPage/components/board/BoardColumnCardCollapsible";
import { cn } from "@/core/utils/ComponentUtils";
import { SkeletonUserAvatarList } from "@/components/UserAvatarList";
import { TRowState } from "@/core/helpers/dnd/types";
import { ROW_IDLE } from "@/core/helpers/dnd/createDndRowEvents";
import { columnRowDndHelpers } from "@/core/helpers/dnd";

export function SkeletonBoardColumnCard({ ref }: { ref?: React.Ref<HTMLDivElement> }): React.JSX.Element {
    return (
        <Card.Root className="border-transparent shadow-transparent" ref={ref}>
            <Card.Header className="relative block py-4">
                <Card.Title className="max-w-[calc(100%_-_theme(spacing.8))] leading-tight">
                    <Skeleton display="inline-block" h="4" className="w-3/4" />
                </Card.Title>
                <Skeleton position="absolute" right="2.5" top="1" display="inline-block" size="8" />
            </Card.Header>
            <Card.Content></Card.Content>
            <Card.Footer className="flex items-end justify-between gap-1.5 pb-4">
                <Skeleton display="inline-block" h="3.5" w="6" />
                <SkeletonUserAvatarList count={2} size="sm" />
            </Card.Footer>
        </Card.Root>
    );
}

const outerStyles: { [Key in TRowState["type"]]?: string } = {
    // We no longer render the draggable item after we have left it
    // as it's space will be taken up by a shadow on adjacent items.
    // Using `display:none` rather than returning `null` so we can always
    // return refs from this component.
    // Keeping the refs allows us to continue to receive events during the drag.
    "is-dragging-and-left-self": "opacity-40",
};

function BoardColumnCard({ card }: { card: ProjectCard.TModel }) {
    const { canDragAndDrop } = useBoard();
    const outerRef = useRef<HTMLDivElement | null>(null);
    const innerRef = useRef<HTMLDivElement | null>(null);
    const [state, setState] = useState<TRowState>(ROW_IDLE);
    const order = card.useField("order");
    const columnUID = card.useField("project_column_uid");

    useEffect(() => {
        if (!canDragAndDrop) {
            return;
        }

        const outer = outerRef.current;
        const inner = innerRef.current;
        invariant(outer && inner);

        return columnRowDndHelpers.row({
            row: card,
            symbolSet: BOARD_DND_SYMBOL_SET,
            draggable: inner,
            dropTarget: outer,
            setState,
            renderPreview({ container }) {
                // Demonstrating using a react portal to generate a preview
                const rect = inner.getBoundingClientRect();
                container.style.width = `${rect.width}px`;
                setState({
                    type: "preview",
                    container,
                    dragging: rect,
                });
            },
        });
    }, [canDragAndDrop, card, order, columnUID]);

    return (
        <>
            <BoardColumnCardDisplay outerRef={outerRef} innerRef={innerRef} state={state} card={card} />
            {state.type === "preview" ? createPortal(<BoardColumnCardDisplay state={state} card={card} />, state.container) : null}
        </>
    );
}

function BoardColumnCardDisplay({
    card,
    state,
    outerRef,
    innerRef,
}: {
    card: ProjectCard.TModel;
    state: TRowState;
    outerRef?: React.Ref<HTMLDivElement | null>;
    innerRef?: React.Ref<HTMLDivElement | null>;
}) {
    const { selectCardViewType, currentCardUIDRef, getRelationshipSelectionActor, isSelectedCard, isDisabledCard } = useBoardController();
    const { filters, canDragAndDrop, navigateWithFilters } = useBoard();
    const isSelectedRelationshipCard = isSelectedCard(card.uid);
    const relationshipSelectionActor = isSelectedRelationshipCard ? getRelationshipSelectionActor(card.uid) : undefined;

    const setFilters = (relationshipType: ProjectCardRelationship.TRelationship) => {
        if (!filters[relationshipType]) {
            filters[relationshipType] = [];
        }

        if (filters[relationshipType].includes(card.uid)) {
            filters[relationshipType] = filters[relationshipType].filter((id) => id !== card.uid);
        } else {
            filters[relationshipType].push(card.uid);
        }

        navigateWithFilters();
    };

    const cardClassName = cn(
        "relative min-w-[theme(spacing.72)_+_theme(spacing.1)]",
        canDragAndDrop
            ? "cursor-pointer touch-pan-y"
            : cn(
                  !selectCardViewType || !isDisabledCard(card.uid) ? "cursor-pointer" : "cursor-not-allowed",
                  !!selectCardViewType && currentCardUIDRef.current === card.uid && "hidden",
                  !!selectCardViewType && isSelectedRelationshipCard && "ring-2",
                  !!selectCardViewType && isDisabledCard(card.uid) && "opacity-30"
              ),
        ["is-dragging", "preview"].includes(state.type) && "ring-2"
    );

    return (
        <ModelRegistry.ProjectCard.Provider model={card} params={{ setFilters }}>
            <Flex gap="2" direction="col" className={outerStyles[state.type]}>
                {state.type === "is-over" && state.closestEdge === "top" ? <BoardColumnCardShadow dragging={state.dragging} /> : null}
                <Box
                    className={cardClassName}
                    ref={outerRef}
                    {...{ [BOARD_CARD_TOUCH_DND_ATTR]: card.uid }}
                    style={relationshipSelectionActor ? ({ "--tw-ring-color": relationshipSelectionActor.color } as React.CSSProperties) : undefined}
                >
                    {relationshipSelectionActor ? (
                        <Box
                            position="absolute"
                            left="3"
                            top="0"
                            z="20"
                            rounded="sm"
                            className="-translate-y-1/2 border bg-background px-1.5 py-0.5 text-[10px] font-medium leading-none shadow-sm"
                            style={{ borderColor: relationshipSelectionActor.color, color: relationshipSelectionActor.color }}
                        >
                            {relationshipSelectionActor.name}
                        </Box>
                    ) : null}
                    <Box ref={innerRef} className="!w-[theme(spacing.72)_+_theme(spacing.1)]">
                        <BoardColumnCardCollapsible isDragging={state.type !== "idle"} />
                    </Box>
                </Box>
                {state.type === "is-over" && state.closestEdge === "bottom" ? <BoardColumnCardShadow dragging={state.dragging} /> : null}
            </Flex>
        </ModelRegistry.ProjectCard.Provider>
    );
}

export function BoardColumnCardShadow({ dragging }: { dragging: DOMRect }) {
    return <Box rounded="xl" w="full" className="flex-shrink-0 bg-secondary/80" style={{ height: dragging.height }} />;
}

export default BoardColumnCard;
