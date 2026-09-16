import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useUpdateCardRelationships from "@/controllers/api/card/useUpdateCardRelationships";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCard, ProjectCardRelationship, ProjectColumn } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import {
    BOARD_CARD_RELATIONSHIP_DND_TYPE,
    BOARD_CARD_TOUCH_DND_ATTR,
    BOARD_CARD_RELATIONSHIP_PREVIEW_EVENT,
    IBoardColumnCardContextParams,
} from "@/pages/BoardPage/components/board/BoardConstants";
import {
    buildCardRelationshipIndex,
    canCreateCardRelationship,
    isRelationshipRenderedInHierarchy,
    TCardRelationshipIndex,
} from "@/pages/BoardPage/components/board/BoardColumnCardHierarchy";
import { draggable } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { Utils } from "@langboard/core/utils";
import { memo, useCallback, useEffect, useReducer, useRef, useState } from "react";
import { relationshipSideCounts } from "./BoardRelationshipGeometry";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

export interface IBoardColumnCardRelationshipProps {
    attributes: Record<string, unknown>;
    compact?: bool;
}

const BoardColumnCardRelationship = memo(({ attributes, compact = false }: IBoardColumnCardRelationshipProps) => {
    const [t] = useTranslation();
    const { model: card } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const { cardsMap, columns, shouldShowArchivedCard } = useBoard();
    const relationships = card.useForeignFieldArray("relationships");
    const [, refresh] = useReducer((value: number) => value + 1, 0);
    const onPositionChanged = useCallback(() => refresh(), []);
    const relatedCards = [
        ...new Set(
            relationships
                .filter((edge) => edge.parent_card_uid === card.uid || edge.child_card_uid === card.uid)
                .map((edge) => (edge.parent_card_uid === card.uid ? edge.child_card_uid : edge.parent_card_uid))
        ),
    ]
        .filter((uid) => uid !== card.uid)
        .map((uid) => cardsMap[uid])
        .filter((model): model is ProjectCard.TModel => !!model);
    const columnOrders = new Map(columns.map((column) => [column.uid, column.order]));
    const counts = relationshipSideCounts(
        columnOrders.get(card.project_column_uid),
        relatedCards.filter(shouldShowArchivedCard).map((model) => ({ uid: model.uid, order: columnOrders.get(model.project_column_uid) }))
    );
    const hasNavigation = counts.left + counts.right > 0;
    return (
        <>
            {[card, ...relatedCards].map((model) => (
                <RelationshipPositionObserver key={model.uid} model={model} columns={columns} onChange={onPositionChanged} />
            ))}
            {(["left", "right"] as const)
                .filter((side) => counts[side] > 0)
                .map((side) => (
                    <Button
                        key={side}
                        size="icon-sm"
                        data-relationship-navigation-side={side}
                        title={`${t("project.Parents")} / ${t("project.Children")}`}
                        className={cn(
                            "absolute top-1/2 z-50 -translate-y-1/2 rounded-full text-xs",
                            side === "left" ? "-left-3" : "-right-3",
                            compact && "size-5 p-0 text-[9px]"
                        )}
                        onClick={(event) => {
                            event.stopPropagation();
                            event.currentTarget.dispatchEvent(new CustomEvent(BOARD_CARD_RELATIONSHIP_PREVIEW_EVENT, { bubbles: true }));
                        }}
                        {...attributes}
                    >
                        +{Math.min(counts[side], 99)}
                    </Button>
                ))}
            <BoardColumnCardRelationshipButton type="parents" attributes={attributes} compact={compact} hasNavigation={hasNavigation} />
            <BoardColumnCardRelationshipButton type="children" attributes={attributes} compact={compact} hasNavigation={hasNavigation} />
        </>
    );
});
BoardColumnCardRelationship.displayName = "Board.ColumnCardRelationship";

function RelationshipPositionObserver({
    model,
    columns,
    onChange,
}: {
    model: ProjectCard.TModel;
    columns: ProjectColumn.TModel[];
    onChange: () => void;
}) {
    const columnUID = model.useField("project_column_uid");
    const archivedAt = model.useField("archived_at");
    useEffect(onChange, [columnUID, archivedAt, onChange]);
    const column = columns.find((item) => item.uid === columnUID);
    return column ? <RelationshipColumnOrderObserver key={column.uid} model={column} onChange={onChange} /> : null;
}

function RelationshipColumnOrderObserver({ model, onChange }: { model: ProjectColumn.TModel; onChange: () => void }) {
    const order = model.useField("order");
    useEffect(onChange, [order, onChange]);
    return null;
}

export interface IBoardColumnCardRelationshipButtonProps {
    type: ProjectCardRelationship.TRelationship;
    attributes: Record<string, unknown>;
    compact: bool;
    hasNavigation: bool;
}

interface IDragLine {
    startX: number;
    startY: number;
    endX: number;
    endY: number;
}

const BoardColumnCardRelationshipButton = memo(({ type, attributes, compact, hasNavigation }: IBoardColumnCardRelationshipButtonProps) => {
    const [t] = useTranslation();
    const { model: card, params } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const { setFilters } = params;
    const isParent = type === "parents";
    const {
        cards,
        cardsMap,
        canDragAndDrop,
        globalRelationshipTypes,
        project,
        shouldShowArchivedCard,
        filterCard,
        filterCardMember,
        filterCardLabels,
        filterCardRelationships,
    } = useBoard();
    const relationships = card.useForeignFieldArray("relationships");
    const hiddenSameColumnCount = relationships.filter((edge) => {
        if ((isParent ? edge.child_card_uid : edge.parent_card_uid) !== card.uid) return false;
        const related = cardsMap[isParent ? edge.parent_card_uid : edge.child_card_uid];
        if (!related || related.project_column_uid !== card.project_column_uid) return false;
        const visible =
            shouldShowArchivedCard(related) &&
            filterCard(related) &&
            filterCardMember(related) &&
            filterCardLabels(related) &&
            filterCardRelationships(related);
        return !isRelationshipRenderedInHierarchy(card, related, visible);
    }).length;
    const buttonRef = useRef<HTMLButtonElement | null>(null);
    const relationshipIndexRef = useRef<TCardRelationshipIndex | undefined>(undefined);
    const highlightedTargetRef = useRef<HTMLElement | null>(null);
    const draggedRef = useRef(false);
    const [dragLine, setDragLine] = useState<IDragLine>();
    const [targetCardUID, setTargetCardUID] = useState<string>();
    const [selectedRelationshipUID, setSelectedRelationshipUID] = useState<string>();
    const [isSaving, setIsSaving] = useState(false);
    const { mutateAsync: updateCardRelationships } = useUpdateCardRelationships({ interceptToast: true });

    useEffect(() => {
        const button = buttonRef.current;
        if (!button || !canDragAndDrop || !globalRelationshipTypes.length) {
            return;
        }

        const clearHighlight = () => {
            highlightedTargetRef.current?.removeAttribute("data-relationship-drop-target");
            highlightedTargetRef.current = null;
        };

        const findTarget = (clientX: number, clientY: number) => {
            const target = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}]`);
            const candidateUID = target?.getAttribute(BOARD_CARD_TOUCH_DND_ATTR);
            const isValid = !!candidateUID && canCreateCardRelationship(cards, card.uid, candidateUID, type, relationshipIndexRef.current);

            clearHighlight();
            if (isValid && target) {
                target.setAttribute("data-relationship-drop-target", "true");
                highlightedTargetRef.current = target;
            }

            return isValid ? candidateUID : undefined;
        };

        return draggable({
            element: button,
            getInitialData: () => ({
                type: BOARD_CARD_RELATIONSHIP_DND_TYPE,
                sourceCardUID: card.uid,
                relationshipType: type,
            }),
            onDragStart({ location }) {
                draggedRef.current = true;
                relationshipIndexRef.current = buildCardRelationshipIndex(cards);
                const rect = button.getBoundingClientRect();
                setDragLine({
                    startX: rect.left + rect.width / 2,
                    startY: rect.top + rect.height / 2,
                    endX: location.current.input.clientX,
                    endY: location.current.input.clientY,
                });
            },
            onDrag({ location }) {
                const { clientX, clientY } = location.current.input;
                findTarget(clientX, clientY);
                setDragLine((current) => (current ? { ...current, endX: clientX, endY: clientY } : current));
            },
            onDrop({ location }) {
                const { clientX, clientY } = location.current.input;
                const nextTargetCardUID = findTarget(clientX, clientY);
                clearHighlight();
                setDragLine(undefined);
                setTargetCardUID(nextTargetCardUID);
                setSelectedRelationshipUID(undefined);
                relationshipIndexRef.current = undefined;
                requestAnimationFrame(() => {
                    draggedRef.current = false;
                });
            },
        });
    }, [canDragAndDrop, card, cards, globalRelationshipTypes.length, type]);

    const closeDialog = () => {
        if (isSaving) {
            return;
        }
        setTargetCardUID(undefined);
        setSelectedRelationshipUID(undefined);
    };

    const saveRelationship = async () => {
        if (!targetCardUID || !selectedRelationshipUID || !canCreateCardRelationship(cards, card.uid, targetCardUID, type)) {
            return;
        }

        const existingRelationships = relationships.map(
            (relationship) =>
                [isParent ? relationship.parent_card_uid : relationship.child_card_uid, relationship.relationship_type_uid] satisfies [string, string]
        );
        setIsSaving(true);
        const promise = updateCardRelationships({
            project_uid: project.uid,
            card_uid: card.uid,
            is_parent: isParent,
            relationships: [...existingRelationships, [targetCardUID, selectedRelationshipUID]],
        });

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);
                handle(error);
                return messageRef.message;
            },
            success: t("successes.Relationships updated successfully."),
            finally: () => setIsSaving(false),
        });

        try {
            await promise;
            setTargetCardUID(undefined);
            setSelectedRelationshipUID(undefined);
        } catch {
            // The toast presents the error while the dialog stays open for retry.
        }
    };

    // Navigation badges own physical direction; these role-specific creation
    // handles appear only on full cards and never overlap those badges.
    if (!hiddenSameColumnCount && (!canDragAndDrop || compact)) {
        return null;
    }

    const targetCard = targetCardUID ? cardsMap[targetCardUID] : undefined;
    const title = canDragAndDrop
        ? t(`card.${isParent ? "Connect parent card" : "Connect child card"}`)
        : t(`project.${new Utils.String.Case(type).toPascal()}`);
    const curveOffset = dragLine ? Math.max(48, Math.abs(dragLine.endX - dragLine.startX) * 0.45) : 0;

    return (
        <>
            <Button
                ref={buttonRef}
                size="icon-sm"
                className={cn(
                    "pointer-events-none absolute z-50 -translate-y-1/2 transform rounded-full text-xs",
                    hasNavigation ? "top-3" : "top-1/2",
                    "opacity-0 transition-opacity hover:bg-primary/70",
                    "group-hover/relationship-card:pointer-events-auto group-hover/relationship-card:opacity-100",
                    "group-focus-within/relationship-card:pointer-events-auto group-focus-within/relationship-card:opacity-100",
                    hiddenSameColumnCount > 0 && "pointer-events-auto opacity-100",
                    compact && "size-5 p-0 text-[9px] opacity-60 transition-opacity hover:opacity-100 focus-visible:opacity-100",
                    isParent ? (compact ? "-left-2" : "-left-3") : compact ? "-right-2" : "-right-3"
                )}
                title={title}
                titleSide={isParent ? "right" : "left"}
                onClick={() => {
                    if (!draggedRef.current) {
                        setFilters(type);
                    }
                }}
                {...attributes}
            >
                {hiddenSameColumnCount ? (
                    <>+{Math.min(hiddenSameColumnCount, 99)}</>
                ) : (
                    <IconComponent icon="git-fork" size={compact ? "3" : "4"} className={isParent ? undefined : "rotate-180"} />
                )}
            </Button>
            {dragLine &&
                createPortal(
                    <svg className="pointer-events-none fixed inset-0 z-[200] size-full overflow-visible" aria-hidden="true">
                        <path
                            d={`M ${dragLine.startX} ${dragLine.startY} C ${dragLine.startX + (isParent ? -curveOffset : curveOffset)} ${
                                dragLine.startY
                            }, ${dragLine.endX + (isParent ? curveOffset : -curveOffset)} ${dragLine.endY}, ${dragLine.endX} ${dragLine.endY}`}
                            fill="none"
                            stroke="hsl(var(--primary))"
                            strokeWidth="2"
                            strokeDasharray="6 5"
                            strokeLinecap="round"
                        />
                    </svg>,
                    document.body
                )}
            <Dialog.Root open={!!targetCard} onOpenChange={(open) => !open && closeDialog()}>
                <Dialog.Content aria-describedby="" withCloseButton={false}>
                    <Dialog.Title>{t("card.Connect cards")}</Dialog.Title>
                    <Dialog.Description>
                        {t("card.Choose a relationship type for {source} and {target}.", {
                            source: card.title,
                            target: targetCard?.title,
                        })}
                    </Dialog.Description>
                    <Flex direction="col" gap="1" mt="3" className="overflow-hidden rounded-md border">
                        {globalRelationshipTypes.map((relationshipType) => {
                            const relationshipName = isParent ? relationshipType.parent_name : relationshipType.child_name;
                            return (
                                <Button
                                    key={relationshipType.uid}
                                    type="button"
                                    variant="ghost"
                                    className={cn(
                                        "justify-start rounded-none border-b last:border-b-0",
                                        selectedRelationshipUID === relationshipType.uid && "bg-accent text-accent-foreground"
                                    )}
                                    onClick={() => setSelectedRelationshipUID(relationshipType.uid)}
                                >
                                    {relationshipName}
                                </Button>
                            );
                        })}
                    </Flex>
                    <Dialog.Footer>
                        <Button type="button" variant="secondary" disabled={isSaving} onClick={closeDialog}>
                            {t("common.Cancel")}
                        </Button>
                        <Button type="button" disabled={!selectedRelationshipUID || isSaving} onClick={saveRelationship}>
                            {t("common.Save")}
                        </Button>
                    </Dialog.Footer>
                </Dialog.Content>
            </Dialog.Root>
        </>
    );
});
BoardColumnCardRelationshipButton.displayName = "Board.ColumnCardRelationshipButton";

export default BoardColumnCardRelationship;
