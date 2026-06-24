"use client";

import { RefObject, useEffect } from "react";
import { reorder } from "@atlaskit/pragmatic-drag-and-drop/reorder";
import { reorderWithEdge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/util/reorder-with-edge";
import { Edge } from "@atlaskit/pragmatic-drag-and-drop-hitbox/dist/types/types";
import { ProjectCard, ProjectColumn } from "@/core/models";
import { canReorderByClosestEdge } from "@/core/helpers/dnd/utils";
import { BOARD_CARD_TOUCH_DND_ATTR, BOARD_COLUMN_TOUCH_DND_ATTR } from "@/pages/BoardPage/components/board/BoardConstants";

interface IUseBoardTouchCardDndProps {
    enabled: bool;
    scrollableRef: RefObject<HTMLDivElement | null>;
    columns: ProjectColumn.TModel[];
    rowsMap: Record<string, ProjectCard.TModel>;
    changeRowOrder: (context: { rowUID: string; order: number; parentUID?: string; undo: () => void }) => void;
}

type TActiveTouchDrag = {
    touchId: number;
    cardUID: string;
    sourceElement: HTMLElement;
    previewElement: HTMLElement | null;
    sourceOpacity: string;
    sourceRect: DOMRect | null;
    startX: number;
    startY: number;
    currentX: number;
    currentY: number;
    timer: number | null;
    isDragging: bool;
};

const TOUCH_DRAG_DELAY_MS = 300;
const TOUCH_MOVE_CANCEL_PX = 8;

const interactiveSelector = "button,a,input,textarea,select,[contenteditable='true'],[role='button']";

function useBoardTouchCardDnd({ enabled, scrollableRef, columns, rowsMap, changeRowOrder }: IUseBoardTouchCardDndProps) {
    useEffect(() => {
        if (!enabled) {
            return;
        }

        const scrollable = scrollableRef.current;
        if (!scrollable) {
            return;
        }

        let active: TActiveTouchDrag | null = null;

        const getRowsByColumnUID = (columnUID: string): ProjectCard.TModel[] => {
            return Object.values(rowsMap)
                .filter((row) => row.project_column_uid === columnUID)
                .sort((a, b) => a.order - b.order);
        };

        const reorderItems = <TValue extends ProjectCard.TModel>({
            list,
            startIndex,
            finishIndex,
        }: {
            list: TValue[];
            startIndex: number;
            finishIndex: number | "last";
        }) => {
            const resolvedFinishIndex = finishIndex === "last" ? list.length - 1 : finishIndex;
            const reordered = reorder({ list, startIndex, finishIndex: resolvedFinishIndex });

            reordered.forEach((item, index) => {
                item.order = index;
            });

            const undo = () => {
                const undoRedorered = reorder({
                    list,
                    startIndex: resolvedFinishIndex,
                    finishIndex: startIndex,
                });

                undoRedorered.forEach((item, index) => {
                    item.order = index;
                });
            };

            return { undo };
        };

        const reorderItemsWithEdge = ({
            list,
            startIndex,
            indexOfTarget,
            closestEdgeOfTarget,
        }: {
            list: ProjectCard.TModel[];
            startIndex: number;
            indexOfTarget: number;
            closestEdgeOfTarget: Edge | null;
        }) => {
            const reordered = reorderWithEdge({
                axis: "vertical",
                list,
                startIndex,
                indexOfTarget,
                closestEdgeOfTarget,
            });

            reordered.forEach((item, index) => {
                item.order = index;
            });

            const undo = () => {
                const undoReordered = reorderWithEdge({
                    axis: "vertical",
                    list,
                    startIndex: indexOfTarget,
                    indexOfTarget: startIndex,
                    closestEdgeOfTarget: closestEdgeOfTarget === "top" ? "bottom" : "top",
                });

                undoReordered.forEach((item, index) => {
                    item.order = index;
                });
            };

            return { undo };
        };

        const moveRow = ({
            draggingRow,
            sourceColumn,
            destinationColumn,
            targetIndex,
        }: {
            draggingRow: ProjectCard.TModel;
            sourceColumn: ProjectColumn.TModel;
            destinationColumn: ProjectColumn.TModel;
            targetIndex: number | "last";
        }) => {
            const updatedCards: Record<string, [number, string | null]> = {};
            let lastIndex = 0;

            Object.values(rowsMap).forEach((row) => {
                if (row.project_column_uid === sourceColumn.uid && row.order > draggingRow.order) {
                    updatedCards[row.uid] = [row.order, null];
                    row.order -= 1;
                    return;
                }

                if (row.project_column_uid !== destinationColumn.uid) {
                    return;
                }

                if (targetIndex === "last") {
                    lastIndex = Math.max(lastIndex, row.order);
                    return;
                }

                if (row.order >= targetIndex) {
                    updatedCards[row.uid] = [row.order, null];
                    row.order += 1;
                }
            });

            updatedCards[draggingRow.uid] = [draggingRow.order, draggingRow.project_column_uid];
            draggingRow.order = targetIndex === "last" ? lastIndex + 1 : targetIndex;
            draggingRow.project_column_uid = destinationColumn.uid;

            const undo = () => {
                Object.entries(updatedCards).forEach(([rowUID, [order, columnUID]]) => {
                    const row = rowsMap[rowUID];
                    if (!row) {
                        return;
                    }

                    row.order = order;
                    if (columnUID) {
                        row.project_column_uid = columnUID;
                    }
                });
            };

            return { undo };
        };

        const cleanupActive = () => {
            if (!active) {
                return;
            }

            if (active.timer !== null) {
                window.clearTimeout(active.timer);
            }

            active.previewElement?.remove();
            active.sourceElement.style.opacity = active.sourceOpacity;
            active = null;
        };

        const beginDrag = () => {
            if (!active || active.isDragging) {
                return;
            }

            const rect = active.sourceElement.getBoundingClientRect();
            const preview = active.sourceElement.cloneNode(true);

            if (!(preview instanceof HTMLElement)) {
                return;
            }

            active.isDragging = true;
            active.sourceRect = rect;
            active.previewElement = preview;
            active.sourceElement.style.opacity = "0.35";

            preview.style.position = "fixed";
            preview.style.left = `${rect.left}px`;
            preview.style.top = `${rect.top}px`;
            preview.style.width = `${rect.width}px`;
            preview.style.height = `${rect.height}px`;
            preview.style.zIndex = "9999";
            preview.style.pointerEvents = "none";
            preview.style.opacity = "0.95";
            preview.style.transform = "translate3d(0, 0, 0)";
            preview.style.transition = "none";

            document.body.appendChild(preview);
        };

        const movePreview = () => {
            if (!active?.isDragging || !active.previewElement || !active.sourceRect) {
                return;
            }

            const deltaX = active.currentX - active.startX;
            const deltaY = active.currentY - active.startY;
            active.previewElement.style.transform = `translate3d(${deltaX}px, ${deltaY}px, 0)`;
        };

        const commitDrop = () => {
            if (!active?.isDragging) {
                return;
            }

            const draggingRow = rowsMap[active.cardUID];
            if (!draggingRow) {
                return;
            }

            const sourceColumn = columns.find((column) => column.uid === draggingRow.project_column_uid);
            if (!sourceColumn) {
                return;
            }

            active.previewElement?.remove();
            active.previewElement = null;

            const dropTarget = document.elementFromPoint(active.currentX, active.currentY);
            if (!(dropTarget instanceof HTMLElement)) {
                return;
            }

            const targetCardElement = dropTarget.closest(`[${BOARD_CARD_TOUCH_DND_ATTR}]`);

            if (targetCardElement instanceof HTMLElement) {
                const targetCardUID = targetCardElement.getAttribute(BOARD_CARD_TOUCH_DND_ATTR);

                if (!targetCardUID || targetCardUID === draggingRow.uid) {
                    return;
                }

                const targetRow = rowsMap[targetCardUID];
                const destinationColumn = columns.find((column) => column.uid === targetRow?.project_column_uid);

                if (!targetRow || !destinationColumn) {
                    return;
                }

                const targetRect = targetCardElement.getBoundingClientRect();
                const closestEdge: Edge = active.currentY < targetRect.top + targetRect.height / 2 ? "top" : "bottom";

                if (sourceColumn.uid === destinationColumn.uid) {
                    if (
                        draggingRow.order === targetRow.order ||
                        !canReorderByClosestEdge({ sourceIndex: draggingRow.order, targetIndex: targetRow.order, closestEdge })
                    ) {
                        return;
                    }

                    const { undo } = reorderItemsWithEdge({
                        list: getRowsByColumnUID(sourceColumn.uid),
                        startIndex: draggingRow.order,
                        indexOfTarget: targetRow.order,
                        closestEdgeOfTarget: closestEdge,
                    });

                    changeRowOrder({ rowUID: draggingRow.uid, order: draggingRow.order, undo });
                    return;
                }

                const finalIndex = closestEdge === "bottom" ? targetRow.order + 1 : targetRow.order;
                const { undo } = moveRow({
                    draggingRow,
                    sourceColumn,
                    destinationColumn,
                    targetIndex: finalIndex,
                });

                changeRowOrder({ rowUID: draggingRow.uid, order: draggingRow.order, parentUID: destinationColumn.uid, undo });
                return;
            }

            const targetColumnElement = dropTarget.closest(`[${BOARD_COLUMN_TOUCH_DND_ATTR}]`);
            const targetColumnUID = targetColumnElement?.getAttribute(BOARD_COLUMN_TOUCH_DND_ATTR);
            const destinationColumn = columns.find((column) => column.uid === targetColumnUID);

            if (!destinationColumn) {
                return;
            }

            if (sourceColumn.uid === destinationColumn.uid) {
                const { undo } = reorderItems({
                    list: getRowsByColumnUID(sourceColumn.uid),
                    startIndex: draggingRow.order,
                    finishIndex: "last",
                });

                changeRowOrder({ rowUID: draggingRow.uid, order: draggingRow.order, undo });
                return;
            }

            const { undo } = moveRow({
                draggingRow,
                sourceColumn,
                destinationColumn,
                targetIndex: "last",
            });

            changeRowOrder({ rowUID: draggingRow.uid, order: draggingRow.order, parentUID: destinationColumn.uid, undo });
        };

        const getChangedTouch = (event: TouchEvent) => {
            if (!active) {
                return null;
            }

            return Array.from(event.changedTouches).find((touch) => touch.identifier === active?.touchId) ?? null;
        };

        const handleTouchStart = (event: TouchEvent) => {
            if (event.touches.length !== 1) {
                return;
            }

            const target = event.target;
            if (!(target instanceof HTMLElement)) {
                return;
            }

            if (target.closest(interactiveSelector)) {
                return;
            }

            const sourceElement = target.closest(`[${BOARD_CARD_TOUCH_DND_ATTR}]`);
            if (!(sourceElement instanceof HTMLElement)) {
                return;
            }

            const cardUID = sourceElement.getAttribute(BOARD_CARD_TOUCH_DND_ATTR);
            const touch = event.changedTouches[0];

            if (!cardUID || !touch) {
                return;
            }

            cleanupActive();

            active = {
                touchId: touch.identifier,
                cardUID,
                sourceElement,
                previewElement: null,
                sourceOpacity: sourceElement.style.opacity,
                sourceRect: null,
                startX: touch.clientX,
                startY: touch.clientY,
                currentX: touch.clientX,
                currentY: touch.clientY,
                timer: window.setTimeout(beginDrag, TOUCH_DRAG_DELAY_MS),
                isDragging: false,
            };
        };

        const handleTouchMove = (event: TouchEvent) => {
            const touch = getChangedTouch(event);
            if (!active || !touch) {
                return;
            }

            active.currentX = touch.clientX;
            active.currentY = touch.clientY;

            if (!active.isDragging) {
                const distance = Math.hypot(active.currentX - active.startX, active.currentY - active.startY);
                if (distance > TOUCH_MOVE_CANCEL_PX) {
                    cleanupActive();
                }
                return;
            }

            event.preventDefault();
            movePreview();
        };

        const handleTouchEnd = (event: TouchEvent) => {
            const touch = getChangedTouch(event);
            if (!active || !touch) {
                return;
            }

            active.currentX = touch.clientX;
            active.currentY = touch.clientY;

            if (active.isDragging) {
                event.preventDefault();
                commitDrop();
            }

            cleanupActive();
        };

        const handleTouchCancel = () => {
            cleanupActive();
        };

        scrollable.addEventListener("touchstart", handleTouchStart, { passive: true });
        scrollable.addEventListener("touchmove", handleTouchMove, { passive: false });
        scrollable.addEventListener("touchend", handleTouchEnd, { passive: false });
        scrollable.addEventListener("touchcancel", handleTouchCancel, { passive: true });

        return () => {
            scrollable.removeEventListener("touchstart", handleTouchStart);
            scrollable.removeEventListener("touchmove", handleTouchMove);
            scrollable.removeEventListener("touchend", handleTouchEnd);
            scrollable.removeEventListener("touchcancel", handleTouchCancel);
            cleanupActive();
        };
    }, [changeRowOrder, columns, enabled, rowsMap, scrollableRef]);
}

export default useBoardTouchCardDnd;
