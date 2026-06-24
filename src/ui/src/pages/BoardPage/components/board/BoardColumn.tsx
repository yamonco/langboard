"use client";

import { memo, type RefObject, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import invariant from "tiny-invariant";
import BoardColumnCard, { BoardColumnCardShadow, SkeletonBoardColumnCard } from "@/pages/BoardPage/components/board/BoardColumnCard";
import { useBoard } from "@/core/providers/BoardProvider";
import { ProjectColumn } from "@/core/models";
import { BoardAddCardProvider } from "@/core/providers/BoardAddCardProvider";
import Box from "@/components/base/Box";
import Card from "@/components/base/Card";
import Flex from "@/components/base/Flex";
import ScrollArea from "@/components/base/ScrollArea";
import ShineBorder from "@/components/base/ShineBorder";
import Skeleton from "@/components/base/Skeleton";
import BoardColumnHeader from "@/pages/BoardPage/components/board/BoardColumnHeader";
import { cn } from "@/core/utils/ComponentUtils";
import BoardColumnAddCard from "@/pages/BoardPage/components/board/BoardColumnAddCard";
import BoardColumnAddCardButton from "@/pages/BoardPage/components/board/BoardColumnAddCardButton";
import useBoardCardCreatedHandlers from "@/controllers/socket/board/useBoardCardCreatedHandlers";
import useBoardUIColumnDeletedHandlers from "@/controllers/socket/board/column/useBoardUIColumnDeletedHandlers";
import { Utils } from "@langboard/core/utils";
import { columnRowDndHelpers } from "@/core/helpers/dnd";
import { TColumnState } from "@/core/helpers/dnd/types";
import {
    BLOCK_BOARD_PANNING_ATTR,
    BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES,
    BOARD_COLUMN_TOUCH_DND_ATTR,
    BOARD_DND_SETTINGS,
    BOARD_DND_SYMBOL_SET,
} from "@/pages/BoardPage/components/board/BoardConstants";
import { COLUMN_IDLE } from "@/core/helpers/dnd/createDndColumnEvents";
import useRowReordered from "@/core/hooks/useRowReordered";
import { useHasRunningBot } from "@/core/stores/BotStatusStore";

export function SkeletonBoardColumn({ cardCount }: { cardCount: number }) {
    return (
        <Card.Root
            className={cn(
                BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES,
                "my-1 grid w-80 flex-shrink-0 grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden border-transparent"
            )}
        >
            <Card.Header className="flex flex-row items-start space-y-0 pb-1 pt-4 text-left font-semibold">
                <Skeleton h="6" className="w-1/3" />
            </Card.Header>
            <Card.Content className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-3">
                <Box pb="2.5" className="overflow-hidden">
                    <Flex direction="col" gap="3">
                        {Array.from({ length: cardCount }).map(() => (
                            <SkeletonBoardColumnCard key={Utils.String.Token.shortUUID()} />
                        ))}
                    </Flex>
                </Box>
            </Card.Content>
        </Card.Root>
    );
}

const stateStyles: { [Key in TColumnState["type"]]: string } = {
    idle: "cursor-grab",
    "is-row-over": "ring-2 ring-primary",
    "is-dragging": "opacity-40 ring-2 ring-primary",
    "is-column-over": "bg-secondary",
};

export interface IBoardColumnProps {
    column: ProjectColumn.TModel;
    updateBoard: () => void;
}

function BoardColumn({ column, updateBoard }: IBoardColumnProps) {
    const scrollableRef = useRef<HTMLDivElement | null>(null);
    const outerFullHeightRef = useRef<HTMLDivElement | null>(null);
    const headerRef = useRef<HTMLDivElement | null>(null);
    const innerRef = useRef<HTMLDivElement | null>(null);
    const [state, setState] = useState<TColumnState>(COLUMN_IDLE);
    const [cardCount, setCardCount] = useState(0);
    const order = column.useField("order");
    const hasRunningBot = useHasRunningBot({ type: "project_column", targetUID: column.uid });

    useEffect(() => {
        const outer = outerFullHeightRef.current;
        const scrollable = scrollableRef.current;
        const header = headerRef.current;
        const inner = innerRef.current;
        invariant(outer);
        invariant(scrollable);
        invariant(header);
        invariant(inner);

        return columnRowDndHelpers.column({
            column,
            symbolSet: BOARD_DND_SYMBOL_SET,
            draggable: header,
            dropTarget: outer,
            scrollable,
            settings: BOARD_DND_SETTINGS,
            setState,
            renderPreview({ container }) {
                // Simple drag preview generation: just cloning the current element.
                // Not using react for this.
                const rect = outer.getBoundingClientRect();
                const preview = outer.cloneNode(true);
                invariant(Utils.Type.isElement(preview, "div"));
                preview.classList.add("ring-2", "ring-primary");
                preview.style.width = `${rect.width}px`;
                preview.style.height = `${rect.height}px`;

                container.appendChild(preview);
            },
        });
    }, [column, order]);

    return (
        <BoardAddCardProvider column={column} viewportRef={scrollableRef} toLastPage={() => {}}>
            <Card.Root
                ref={outerFullHeightRef}
                {...{ [BOARD_COLUMN_TOUCH_DND_ATTR]: column.uid }}
                className={cn(
                    BOARD_COLUMN_MAX_HEIGHT_CLASS_NAMES,
                    "relative my-1 grid w-72 flex-shrink-0 snap-center grid-rows-[auto_minmax(0,1fr)_auto] overflow-hidden shadow-md",
                    "shadow-black/30 ring-primary dark:shadow-border/90 sm:w-80",
                    stateStyles[state.type]
                )}
            >
                {hasRunningBot && <ShineBorder />}
                <BoardColumnHeader isDragging={state.type !== "idle"} column={column} headerProps={{ ref: headerRef }} />
                <ScrollArea.Root
                    className="min-h-0 flex-1"
                    viewportRef={scrollableRef}
                    viewportClassName="!overflow-y-auto overscroll-contain touch-pan-y"
                    mutable={`${state.type}:${cardCount}`}
                >
                    <Card.Content className="flex min-h-0 touch-pan-y flex-col gap-2 p-3" {...{ [BLOCK_BOARD_PANNING_ATTR]: true }} ref={innerRef}>
                        <BoardColumnCardList
                            column={column}
                            updateBoard={updateBoard}
                            scrollableRef={scrollableRef}
                            onCardCountChange={setCardCount}
                        />
                        {state.type === "is-row-over" && !state.isOverChildRow && <BoardColumnCardShadow dragging={state.dragging} />}
                        <BoardColumnAddCard />
                    </Card.Content>
                </ScrollArea.Root>
                <Card.Footer className="shrink-0 px-3 py-2">
                    <BoardColumnAddCardButton />
                </Card.Footer>
            </Card.Root>
        </BoardAddCardProvider>
    );
}

/**
 * A memoized component for rendering out the card.
 *
 * Created so that state changes to the column don't require all cards to be rendered
 */
interface IBoardColumnCardListProps extends IBoardColumnProps {
    scrollableRef: RefObject<HTMLDivElement | null>;
    onCardCountChange: (cardCount: number) => void;
}

const BoardColumnCardList = memo(({ column, updateBoard, scrollableRef, onCardCountChange }: IBoardColumnCardListProps) => {
    const { project, socket, filters, filterCard, shouldShowArchivedCard, filterCardMember, filterCardLabels, filterCardRelationships } = useBoard();
    const updater = useReducer((x) => x + 1, 0);
    const [_, forceUpdate] = updater;
    const cardCreatedHandlers = useMemo(
        () =>
            useBoardCardCreatedHandlers({
                projectUID: project.uid,
                columnUID: column.uid,
                callback: () => {
                    forceUpdate();
                },
            }),
        [project, column, forceUpdate]
    );
    const columnDeletedHandlers = useMemo(
        () =>
            useBoardUIColumnDeletedHandlers({
                project,
                callback: () => {
                    if (!column.is_archive) {
                        return;
                    }

                    forceUpdate();
                    updateBoard();
                },
            }),
        [project, column, updateBoard, forceUpdate]
    );
    const otherHandlers = useMemo(() => [cardCreatedHandlers, columnDeletedHandlers], [cardCreatedHandlers, columnDeletedHandlers]);
    const { rows: columnCards } = useRowReordered({
        type: "ProjectCard",
        eventNameParams: { uid: column.uid },
        topicId: project.uid,
        rowFilter: (model) => {
            return (
                model.project_column_uid === column.uid &&
                (!column.is_archive || shouldShowArchivedCard(model)) &&
                filterCard(model) &&
                filterCardMember(model) &&
                filterCardLabels(model) &&
                filterCardRelationships(model)
            );
        },
        rowDependencies: [filters, filterCard, filterCardMember, filterCardLabels, filterCardRelationships],
        columnUID: column.uid,
        socket,
        updater,
        otherHandlers,
    });

    useEffect(() => {
        onCardCountChange(columnCards.length);
    }, [columnCards.length, onCardCountChange]);

    const virtualizer = useVirtualizer({
        count: columnCards.length,
        getScrollElement: () => scrollableRef.current,
        estimateSize: () => 126,
        overscan: 10,
        getItemKey: (index) => columnCards[index]?.uid ?? index,
    });
    const virtualItems = virtualizer.getVirtualItems();
    const totalSize = virtualizer.getTotalSize();

    return (
        <Box className="relative w-full flex-shrink-0" style={{ height: `${totalSize}px` }}>
            {virtualItems.map((virtualRow) => {
                const card = columnCards[virtualRow.index];
                if (!card) {
                    return null;
                }

                return (
                    <Box
                        key={card.uid}
                        ref={virtualizer.measureElement}
                        data-index={virtualRow.index}
                        className="absolute left-0 top-0 w-full pb-2"
                        style={{ transform: `translateY(${virtualRow.start}px)` }}
                    >
                        <BoardColumnCard card={card} />
                    </Box>
                );
            })}
        </Box>
    );
});

export default BoardColumn;
