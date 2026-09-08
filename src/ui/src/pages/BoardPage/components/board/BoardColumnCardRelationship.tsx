import Button from "@/components/base/Button";
import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useUpdateCardRelationships from "@/controllers/api/card/useUpdateCardRelationships";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectCardRelationship } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardController } from "@/core/providers/BoardController";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import {
    BOARD_CARD_RELATIONSHIP_DND_TYPE,
    BOARD_CARD_TOUCH_DND_ATTR,
    IBoardColumnCardContextParams,
} from "@/pages/BoardPage/components/board/BoardConstants";
import { canCreateCardRelationship } from "@/pages/BoardPage/components/board/BoardColumnCardHierarchy";
import { draggable } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import { Utils } from "@langboard/core/utils";
import { memo, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

export interface IBoardColumnCardRelationshipProps {
    attributes: Record<string, unknown>;
    compact?: bool;
}

const BoardColumnCardRelationship = memo(({ attributes, compact = false }: IBoardColumnCardRelationshipProps) => {
    return (
        <>
            <BoardColumnCardRelationshipButton type="parents" attributes={attributes} compact={compact} />
            <BoardColumnCardRelationshipButton type="children" attributes={attributes} compact={compact} />
        </>
    );
});
BoardColumnCardRelationship.displayName = "Board.ColumnCardRelationship";

export interface IBoardColumnCardRelationshipButtonProps {
    type: ProjectCardRelationship.TRelationship;
    attributes: Record<string, unknown>;
    compact: bool;
}

interface IDragLine {
    startX: number;
    startY: number;
    endX: number;
    endY: number;
}

const BoardColumnCardRelationshipButton = memo(({ type, attributes, compact }: IBoardColumnCardRelationshipButtonProps) => {
    const [t] = useTranslation();
    const { model: card, params } = ModelRegistry.ProjectCard.useContext<IBoardColumnCardContextParams>();
    const { setFilters } = params;
    const isParent = type === "parents";
    const { filterRelationships } = useBoardController();
    const { cards, cardsMap, canDragAndDrop, globalRelationshipTypes, project } = useBoard();
    const flatRelationships = card.useForeignFieldArray("relationships");
    const relationships = filterRelationships(card.uid, flatRelationships, isParent);
    const visibleRelationshipCount = relationships.filter((relationship) => {
        const relatedCardUID = isParent ? relationship.parent_card_uid : relationship.child_card_uid;
        return cardsMap[relatedCardUID]?.project_column_uid !== card.project_column_uid;
    }).length;
    const buttonRef = useRef<HTMLButtonElement | null>(null);
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
            const isValid = !!candidateUID && canCreateCardRelationship(cards, card.uid, candidateUID, type);

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

    if (!visibleRelationshipCount && !canDragAndDrop) {
        return null;
    }

    const relationshipCount = visibleRelationshipCount > 99 ? "99" : visibleRelationshipCount;
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
                    "absolute top-1/2 z-30 block -translate-y-1/2 transform rounded-full text-xs hover:bg-primary/70",
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
                {visibleRelationshipCount ? (
                    <>+{relationshipCount}</>
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
