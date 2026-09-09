import Button from "@/components/base/Button";
import { useBoard } from "@/core/providers/BoardProvider";
import {
    BOARD_CARD_FOCUS_EVENT,
    BOARD_CARD_TOUCH_DND_ATTR,
    BOARD_COLUMN_TOUCH_DND_ATTR,
    IBoardCardFocusEventDetail,
} from "@/pages/BoardPage/components/board/BoardConstants";
import { memo, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";

interface IBoardCardRelationshipOverlayProps {
    scrollableRef: React.RefObject<HTMLDivElement | null>;
}

interface IVisibleEdge {
    uid: string;
    label: string;
    path: string;
    labelX: number;
    labelY: number;
}

interface IEdgePreview {
    columnUID: string;
    cardUID: string;
    title: string;
    columnName: string;
    count: number;
    side: "left" | "right";
}

interface IOverlayLayout {
    edges: IVisibleEdge[];
    previews: IEdgePreview[];
}

const getCardElement = (cardUID: string) => document.querySelector<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}="${CSS.escape(cardUID)}"]`);
const RELATIONSHIP_PREVIEW_ATTR = "data-board-relationship-preview";

const BoardCardRelationshipOverlay = memo(({ scrollableRef }: IBoardCardRelationshipOverlayProps) => {
    const { cardsMap, columns } = useBoard();
    const [hoveredCardUID, setHoveredCardUID] = useState<string>();
    const [layout, setLayout] = useState<IOverlayLayout>({ edges: [], previews: [] });
    const columnsMap = useMemo(() => new Map(columns.map((column) => [column.uid, column])), [columns]);

    useEffect(() => {
        const scrollable = scrollableRef.current;
        if (!scrollable) {
            return;
        }

        const getCardUID = (target: EventTarget | null) =>
            target instanceof Element
                ? target.closest<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}]`)?.getAttribute(BOARD_CARD_TOUCH_DND_ATTR)
                : undefined;
        const onPointerOver = (event: PointerEvent) => {
            const cardUID = getCardUID(event.target);
            if (cardUID) {
                setHoveredCardUID(cardUID);
            }
        };
        const onPointerOut = (event: PointerEvent) => {
            const sourceCardUID = getCardUID(event.target);
            const nextElement = event.relatedTarget instanceof Element ? event.relatedTarget : undefined;
            const nextCardUID = getCardUID(nextElement);
            if (nextElement?.closest(`[${RELATIONSHIP_PREVIEW_ATTR}]`)) {
                return;
            }
            if (sourceCardUID && sourceCardUID !== nextCardUID) {
                setHoveredCardUID(undefined);
            }
        };

        scrollable.addEventListener("pointerover", onPointerOver);
        scrollable.addEventListener("pointerout", onPointerOut);
        return () => {
            scrollable.removeEventListener("pointerover", onPointerOver);
            scrollable.removeEventListener("pointerout", onPointerOut);
        };
    }, [scrollableRef]);

    useEffect(() => {
        const scrollable = scrollableRef.current;
        const sourceCard = hoveredCardUID ? cardsMap[hoveredCardUID] : undefined;
        if (!scrollable || !sourceCard) {
            setLayout({ edges: [], previews: [] });
            return;
        }

        let frame = 0;
        const updateLayout = () => {
            cancelAnimationFrame(frame);
            frame = requestAnimationFrame(() => {
                const sourceElement = getCardElement(sourceCard.uid);
                if (!sourceElement) {
                    setLayout({ edges: [], previews: [] });
                    return;
                }

                const viewport = scrollable.getBoundingClientRect();
                const sourceRect = sourceElement.getBoundingClientRect();
                const sourceColumn = columnsMap.get(sourceCard.project_column_uid);
                const edges: IVisibleEdge[] = [];
                const previewGroups = new Map<string, IEdgePreview>();
                const seenCardUIDs = new Set<string>();

                sourceCard.relationships.forEach((relationship) => {
                    const sourceIsParent = relationship.parent_card_uid === sourceCard.uid;
                    const relatedCardUID = sourceIsParent ? relationship.child_card_uid : relationship.parent_card_uid;
                    const relatedCard = cardsMap[relatedCardUID];
                    if (!relatedCard || relatedCard.project_column_uid === sourceCard.project_column_uid || seenCardUIDs.has(relatedCardUID)) {
                        return;
                    }
                    seenCardUIDs.add(relatedCardUID);

                    const targetElement = getCardElement(relatedCardUID);
                    const targetRect = targetElement?.getBoundingClientRect();
                    const isVisible =
                        !!targetRect &&
                        targetRect.right >= viewport.left &&
                        targetRect.left <= viewport.right &&
                        targetRect.bottom >= viewport.top &&
                        targetRect.top <= viewport.bottom;
                    const targetColumn = columnsMap.get(relatedCard.project_column_uid);
                    const targetIsLeft = (targetColumn?.order ?? 0) < (sourceColumn?.order ?? 0);

                    if (isVisible && targetRect) {
                        const relationshipType = relationship.relationship_type;
                        if (!relationshipType) {
                            return;
                        }
                        const startX = targetIsLeft ? sourceRect.left : sourceRect.right;
                        const endX = targetIsLeft ? targetRect.right : targetRect.left;
                        const startY = sourceRect.top + sourceRect.height / 2;
                        const endY = targetRect.top + targetRect.height / 2;
                        const curve = Math.max(56, Math.abs(endX - startX) * 0.42);
                        const direction = targetIsLeft ? -1 : 1;
                        const firstControlX = startX + curve * direction;
                        const secondControlX = endX - curve * direction;
                        edges.push({
                            uid: relationship.uid,
                            label: sourceIsParent ? relationshipType.child_name : relationshipType.parent_name,
                            path: `M ${startX} ${startY} C ${firstControlX} ${startY}, ${secondControlX} ${endY}, ${endX} ${endY}`,
                            labelX: (startX + endX) / 2,
                            labelY: (startY + endY) / 2 - 6,
                        });
                        return;
                    }

                    const side = targetIsLeft ? "left" : "right";
                    const key = `${side}:${relatedCard.project_column_uid}`;
                    const existingPreview = previewGroups.get(key);
                    if (existingPreview) {
                        existingPreview.count += 1;
                    } else {
                        previewGroups.set(key, {
                            columnUID: relatedCard.project_column_uid,
                            cardUID: relatedCardUID,
                            title: relatedCard.title,
                            columnName: targetColumn?.name ?? "",
                            count: 1,
                            side,
                        });
                    }
                });

                setLayout({ edges, previews: [...previewGroups.values()] });
            });
        };

        updateLayout();
        window.addEventListener("resize", updateLayout);
        scrollable.addEventListener("scroll", updateLayout, true);
        return () => {
            cancelAnimationFrame(frame);
            window.removeEventListener("resize", updateLayout);
            scrollable.removeEventListener("scroll", updateLayout, true);
        };
    }, [cardsMap, columnsMap, hoveredCardUID, scrollableRef]);

    const focusPreview = (preview: IEdgePreview) => {
        const columnElement = document.querySelector<HTMLElement>(`[${BOARD_COLUMN_TOUCH_DND_ATTR}="${CSS.escape(preview.columnUID)}"]`);
        columnElement?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
        document.dispatchEvent(
            new CustomEvent<IBoardCardFocusEventDetail>(BOARD_CARD_FOCUS_EVENT, {
                detail: { cardUID: preview.cardUID, columnUID: preview.columnUID },
            })
        );
    };

    if (!hoveredCardUID || (!layout.edges.length && !layout.previews.length)) {
        return null;
    }

    const viewport = scrollableRef.current?.getBoundingClientRect();

    return createPortal(
        <>
            <svg className="pointer-events-none fixed inset-0 z-40 size-full overflow-visible" aria-hidden="true">
                <defs>
                    <marker id="board-relationship-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                        <path d="M 0 0 L 8 4 L 0 8 z" fill="hsl(var(--primary))" />
                    </marker>
                </defs>
                {layout.edges.map((edge) => (
                    <g key={edge.uid}>
                        <path
                            d={edge.path}
                            fill="none"
                            stroke="hsl(var(--primary))"
                            strokeWidth="2"
                            strokeLinecap="round"
                            markerEnd="url(#board-relationship-arrow)"
                        />
                        <text
                            x={edge.labelX}
                            y={edge.labelY}
                            textAnchor="middle"
                            className="fill-foreground text-[10px] font-medium"
                            paintOrder="stroke"
                            stroke="hsl(var(--background))"
                            strokeWidth="4"
                        >
                            {edge.label}
                        </text>
                    </g>
                ))}
            </svg>
            {layout.previews.map((preview, index) => (
                <Button
                    key={`${preview.side}:${preview.columnUID}`}
                    type="button"
                    {...{ [RELATIONSHIP_PREVIEW_ATTR]: true }}
                    variant="secondary"
                    className="fixed z-40 h-auto max-w-56 justify-start whitespace-normal border border-primary/30 px-3 py-2 text-left shadow-lg"
                    style={{
                        [preview.side]:
                            preview.side === "left" ? (viewport?.left ?? 0) + 12 : window.innerWidth - (viewport?.right ?? window.innerWidth) + 12,
                        top: (viewport?.top ?? 80) + 16 + index * 58,
                    }}
                    onClick={() => focusPreview(preview)}
                    onPointerLeave={() => setHoveredCardUID(undefined)}
                >
                    <span className="min-w-0">
                        <span className="block truncate text-xs font-semibold">{preview.title}</span>
                        <span className="block truncate text-[10px] text-muted-foreground">
                            {preview.columnName}
                            {preview.count > 1 ? ` · +${preview.count - 1}` : ""}
                        </span>
                    </span>
                </Button>
            ))}
        </>,
        document.body
    );
});
BoardCardRelationshipOverlay.displayName = "Board.CardRelationshipOverlay";

export default BoardCardRelationshipOverlay;
