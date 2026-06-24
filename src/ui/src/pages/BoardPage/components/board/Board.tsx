"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import invariant from "tiny-invariant";
import BoardColumn, { SkeletonBoardColumn } from "@/pages/BoardPage/components/board/BoardColumn";
import { bindAll } from "bind-event-listener";
import { CleanupFn } from "@atlaskit/pragmatic-drag-and-drop/dist/types/internal-types";
import { useBoard } from "@/core/providers/BoardProvider";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import ScrollArea from "@/components/base/ScrollArea";
import BoardColumnAdd from "@/pages/BoardPage/components/board/BoardColumnAdd";
import useChangeProjectColumnOrder from "@/controllers/api/board/useChangeProjectColumnOrder";
import useChangeCardOrder from "@/controllers/api/board/useChangeCardOrder";
import { BLOCK_BOARD_PANNING_ATTR, BOARD_DND_SETTINGS, BOARD_DND_SYMBOL_SET } from "@/pages/BoardPage/components/board/BoardConstants";
import { SkeletonUserAvatarList } from "@/components/UserAvatarList";
import { SkeletonBoardFilter } from "@/pages/BoardPage/components/board/BoardFilter";
import { Utils } from "@langboard/core/utils";
import { columnRowDndHelpers } from "@/core/helpers/dnd";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useColumnReordered from "@/core/hooks/useColumnReordered";
import { useBoardController } from "@/core/providers/BoardController";
import { cn } from "@/core/utils/ComponentUtils";
import useBoardTouchCardDnd from "@/pages/BoardPage/components/board/useBoardTouchCardDnd";

export function SkeletonBoard() {
    const [cardCounts, setCardCounts] = useState([1, 3, 2]);

    useEffect(() => {
        let timeout: NodeJS.Timeout | null = null;

        const updateCardCounts = () => {
            setCardCounts((prev) => {
                return prev.map((count) => {
                    if (count === 1) {
                        count = 3;
                    } else if (count === 3) {
                        count = 2;
                    } else {
                        count = 1;
                    }

                    return count;
                });
            });
        };

        timeout = setTimeout(updateCardCounts, 2000);

        return () => {
            clearTimeout(timeout!);
            timeout = null;
        };
    }, []);

    return (
        <>
            <Flex justify="between" px="4" pt="4" wrap>
                <SkeletonUserAvatarList count={6} size={{ initial: "sm", xs: "default" }} spacing="none" />
                <Flex items="center" gap="1">
                    <SkeletonBoardFilter />
                </Flex>
            </Flex>

            <Box
                position="relative"
                h="full"
                className={cn(
                    "max-h-[calc(100dvh_-_theme(spacing.28)_-_theme(spacing.2)_-_theme(spacing.16))]",
                    "overflow-hidden md:max-h-[calc(100dvh_-_theme(spacing.28)_-_theme(spacing.2))]"
                )}
            >
                <Box size="full" className="rounded-[inherit]">
                    <Flex direction="row" items="start" gap="10" p="4">
                        {cardCounts.map((count) => (
                            <SkeletonBoardColumn key={Utils.String.Token.shortUUID()} cardCount={count} />
                        ))}
                    </Flex>
                </Box>
            </Box>
        </>
    );
}

export function Board() {
    const scrollableRef = useRef<HTMLDivElement | null>(null);

    return (
        <ScrollArea.Root
            className={cn(
                "h-[calc(100dvh_-_theme(spacing.28)_-_theme(spacing.2)_-_theme(spacing.16))]",
                "min-h-0 md:h-[calc(100dvh_-_theme(spacing.28)_-_theme(spacing.2))]"
            )}
            viewportClassName="!overflow-x-auto"
            viewportRef={scrollableRef}
        >
            <Flex direction="row" items="start" gap={{ initial: "6", sm: "8" }} p="4" h="full" className="min-h-0">
                <BoardDisplay scrollableRef={scrollableRef} />
            </Flex>
            <ScrollArea.Bar orientation="horizontal" />
        </ScrollArea.Root>
    );
}

function BoardDisplay({ scrollableRef }: { scrollableRef: React.RefObject<HTMLDivElement | null> }) {
    const { chatResizableSidebar } = useBoardController();
    const { project, columns: flatColumns, cardsMap, socket, canDragAndDrop } = useBoard();
    const updater = useReducer((x) => x + 1, 0);
    const [_, forceUpdate] = updater;
    const { columns } = useColumnReordered({
        type: "ProjectColumn",
        topicId: project.uid,
        eventNameParams: { uid: project.uid },
        columns: flatColumns,
        socket,
        updater,
    });
    const { mutate: changeColumnOrderMutate } = useChangeProjectColumnOrder();
    const { mutate: changeCardOrderMutate } = useChangeCardOrder();

    const setupApiErrors = useCallback((error: unknown, undo: () => void) => {
        const { handle } = setupApiErrorHandler({
            code: {
                after: undo,
            },
            wildcard: {
                after: undo,
            },
        });

        handle(error);
    }, []);

    const changeColumnOrder = useCallback(
        ({ columnUID, order, undo }: { columnUID: string; order: number; undo: () => void }) => {
            changeColumnOrderMutate(
                { project_uid: project.uid, project_column_uid: columnUID, order },
                {
                    onError: (error) => setupApiErrors(error, undo),
                    onSettled: forceUpdate,
                }
            );
        },
        [changeColumnOrderMutate, forceUpdate, project, setupApiErrors]
    );

    const changeRowOrder = useCallback(
        ({ rowUID, order, parentUID, undo }: { rowUID: string; order: number; parentUID?: string; undo: () => void }) => {
            changeCardOrderMutate(
                { project_uid: project.uid, parent_uid: parentUID, card_uid: rowUID, order },
                {
                    onError: (error) => setupApiErrors(error, undo),
                    onSettled: forceUpdate,
                }
            );
        },
        [changeCardOrderMutate, forceUpdate, project, setupApiErrors]
    );

    useBoardTouchCardDnd({
        enabled: canDragAndDrop,
        scrollableRef,
        columns,
        rowsMap: cardsMap,
        changeRowOrder,
    });

    useEffect(() => {
        const scrollable = scrollableRef.current;
        invariant(scrollable);

        return columnRowDndHelpers.root({
            columns,
            rowsMap: cardsMap,
            columnKeyInRow: "project_column_uid",
            symbolSet: BOARD_DND_SYMBOL_SET,
            scrollable,
            settings: BOARD_DND_SETTINGS,
            changeColumnOrder,
            changeRowOrder,
        });
    }, [cardsMap, changeColumnOrder, changeRowOrder, chatResizableSidebar, columns, scrollableRef]);

    // Panning the board
    useEffect(() => {
        let cleanupActive: CleanupFn | null = null;
        const scrollable = scrollableRef.current;
        invariant(scrollable);

        function begin({ startX }: { startX: number }) {
            let lastX = startX;

            const cleanupEvents = bindAll(
                window,
                [
                    {
                        type: "pointermove",
                        listener(event) {
                            const currentX = event.clientX;
                            const diffX = lastX - currentX;

                            lastX = currentX;
                            scrollable?.scrollBy({ left: diffX });
                        },
                    },
                    // stop panning if we see any of these events
                    ...(["pointercancel", "pointerup", "pointerdown", "keydown", "resize", "click", "visibilitychange"] as const).map(
                        (eventName) => ({ type: eventName, listener: () => cleanupEvents() })
                    ),
                ],
                // need to make sure we are not after the "pointerdown" on the scrollable
                // Also this is helpful to make sure we always hear about events from this point
                { capture: true }
            );

            cleanupActive = cleanupEvents;
        }

        const cleanupStart = bindAll(scrollable, [
            {
                type: "pointerdown",
                listener(event) {
                    if (!(event.target instanceof HTMLElement)) {
                        return;
                    }
                    // ignore interactive elements
                    if (event.target.closest(`[${BLOCK_BOARD_PANNING_ATTR}]`)) {
                        return;
                    }

                    begin({ startX: event.clientX });
                },
            },
        ]);

        return () => {
            cleanupStart();
            cleanupActive?.();
        };
    }, []);

    return (
        <>
            {columns.map((column) => (
                <BoardColumn key={`board-columnr-${column.uid}`} column={column} updateBoard={forceUpdate} />
            ))}
            {canDragAndDrop && <BoardColumnAdd />}
        </>
    );
}
