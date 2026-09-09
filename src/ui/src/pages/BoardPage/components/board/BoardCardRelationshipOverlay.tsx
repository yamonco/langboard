import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import { useBoard } from "@/core/providers/BoardProvider";
import {
    getRelationshipDirection,
    intersectRelationshipRects,
    relationshipCurve,
    type TRelationshipDirection,
} from "@/pages/BoardPage/components/board/BoardRelationshipGeometry";
import {
    BOARD_CARD_FOCUS_EVENT,
    BOARD_CARD_LOCATION_EVENT,
    BOARD_CARD_TOUCH_DND_ATTR,
    BOARD_COLUMN_TOUCH_DND_ATTR,
    IBoardCardFocusEventDetail,
    IBoardCardLocationEventDetail,
} from "@/pages/BoardPage/components/board/BoardConstants";
import { memo, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { relationshipFocusAction } from "@/pages/BoardPage/components/board/BoardRelationshipFocus";
import { createRelationshipHoverIntent } from "@/pages/BoardPage/components/board/BoardRelationshipHoverIntent";

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

interface IPreviewTarget {
    columnUID: string;
    cardUID: string;
    title: string;
    columnName: string;
    label: string;
    sourceIsParent: boolean;
    relationshipUID: string;
}

interface IEdgePreview {
    side: TRelationshipDirection;
    targets: IPreviewTarget[];
    left: number;
    top: number;
    width: number;
    height: number;
}

interface IOverlayLayout {
    edges: IVisibleEdge[];
    previews: IEdgePreview[];
}

const getCardElements = (cardUID: string) =>
    Array.from(document.querySelectorAll<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}="${CSS.escape(cardUID)}"]`));
const getColumnElement = (columnUID: string) => document.querySelector<HTMLElement>(`[${BOARD_COLUMN_TOUCH_DND_ATTR}="${CSS.escape(columnUID)}"]`);
const RELATIONSHIP_PREVIEW_ATTR = "data-board-relationship-preview";

const BoardCardRelationshipOverlay = memo(({ scrollableRef }: IBoardCardRelationshipOverlayProps) => {
    const { cardsMap, columns, filters } = useBoard();
    const [hoveredElement, setHoveredElement] = useState<HTMLElement | null>(null);
    const hoveredCardUID = hoveredElement?.getAttribute(BOARD_CARD_TOUCH_DND_ATTR);
    const hoverIntent = useMemo(() => createRelationshipHoverIntent({ onOpen: setHoveredElement, onClose: () => setHoveredElement(null) }), []);
    const keepOpen = hoverIntent.keepOpen;
    const scheduleClose = hoverIntent.pointerLeave;
    const [layout, setLayout] = useState<IOverlayLayout>({ edges: [], previews: [] });
    const columnsMap = useMemo(() => new Map(columns.map((column) => [column.uid, column])), [columns]);

    useEffect(() => {
        const source = hoveredElement?.querySelector<HTMLButtonElement>("[data-board-card-open]");
        if (!source || !layout.previews.length) return;
        const onKeyDown = (event: KeyboardEvent) => {
            const buttons = Array.from(document.querySelectorAll<HTMLButtonElement>(`[${RELATIONSHIP_PREVIEW_ATTR}] button`));
            const previewIndex = buttons.indexOf(document.activeElement as HTMLButtonElement);
            const action = relationshipFocusAction(event.key, event.shiftKey, document.activeElement === source, previewIndex, buttons.length);
            if (!action) return;
            // Leaving the last preview resumes the browser's normal Tab from the title.
            if (action !== "next") event.preventDefault();
            if (action === "first") buttons[0]?.focus({ preventScroll: true });
            else {
                source.focus({ preventScroll: true });
                if (action !== "source") setHoveredElement(null);
            }
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [hoveredElement, layout.previews.length]);

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
            if (!cardUID || cardUID === getCardUID(event.relatedTarget) || !cardsMap[cardUID]?.relationships.length) return;
            const cardElement = (event.target as Element).closest<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}]`);
            if (cardElement) hoverIntent.pointerEnter(cardElement);
        };
        const onFocusIn = (event: FocusEvent) => {
            const cardUID = getCardUID(event.target);
            if (!cardUID || cardUID === getCardUID(event.relatedTarget) || !cardsMap[cardUID]?.relationships.length) return;
            const cardElement = (event.target as Element).closest<HTMLElement>(`[${BOARD_CARD_TOUCH_DND_ATTR}]`);
            if (cardElement) hoverIntent.openImmediately(cardElement);
        };
        const onPointerOut = (event: PointerEvent | FocusEvent) => {
            const sourceCardUID = getCardUID(event.target);
            const nextElement = event.relatedTarget instanceof Element ? event.relatedTarget : undefined;
            const nextCardUID = getCardUID(nextElement);
            if (nextElement?.closest(`[${RELATIONSHIP_PREVIEW_ATTR}]`)) {
                return;
            }
            if (sourceCardUID && sourceCardUID !== nextCardUID) {
                scheduleClose();
            }
        };

        scrollable.addEventListener("pointerover", onPointerOver);
        scrollable.addEventListener("pointerout", onPointerOut);
        scrollable.addEventListener("focusin", onFocusIn);
        scrollable.addEventListener("focusout", onPointerOut);
        const close = hoverIntent.close;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === "Escape") close();
        };
        scrollable.addEventListener("dragstart", close);
        window.addEventListener("keydown", onKeyDown);
        return () => {
            hoverIntent.dispose();
            scrollable.removeEventListener("pointerover", onPointerOver);
            scrollable.removeEventListener("pointerout", onPointerOut);
            scrollable.removeEventListener("focusin", onFocusIn);
            scrollable.removeEventListener("focusout", onPointerOut);
            scrollable.removeEventListener("dragstart", close);
            window.removeEventListener("keydown", onKeyDown);
        };
    }, [cardsMap, scrollableRef, hoverIntent, scheduleClose]);

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
                const sourceElement = hoveredElement;
                if (!sourceElement?.isConnected) {
                    setLayout({ edges: [], previews: [] });
                    return;
                }

                const navigationTop = document.querySelector(".board-floating-navigation")?.getBoundingClientRect().top;
                const viewport = intersectRelationshipRects(scrollable.getBoundingClientRect(), {
                    left: 0,
                    top: 0,
                    right: window.innerWidth,
                    bottom: Math.min(window.innerHeight, navigationTop ?? window.innerHeight),
                });
                if (!viewport) {
                    setLayout({ edges: [], previews: [] });
                    return;
                }
                const clipForColumn = (columnUID: string) => {
                    const column = getColumnElement(columnUID);
                    const scrollport = column?.querySelector<HTMLElement>("[data-radix-scroll-area-viewport]");
                    return intersectRelationshipRects((scrollport ?? column)?.getBoundingClientRect() ?? viewport, viewport);
                };
                const sourceClip = clipForColumn(sourceCard.project_column_uid);
                const sourceRect = sourceClip && intersectRelationshipRects(sourceElement.getBoundingClientRect(), sourceClip);
                if (!sourceRect) {
                    setLayout({ edges: [], previews: [] });
                    return;
                }
                const sourceY = (sourceRect.top + sourceRect.bottom) / 2;
                const edges: IVisibleEdge[] = [];
                const previewGroups = new Map<TRelationshipDirection, IPreviewTarget[]>();
                const seenCardUIDs = new Set<string>();

                sourceCard.relationships.forEach((relationship) => {
                    const sourceIsParent = relationship.parent_card_uid === sourceCard.uid;
                    const relatedCardUID = sourceIsParent ? relationship.child_card_uid : relationship.parent_card_uid;
                    const relatedCard = cardsMap[relatedCardUID];
                    const relationshipType = relationship.relationship_type;
                    if (!relatedCard || !relationshipType || seenCardUIDs.has(relatedCardUID)) {
                        return;
                    }
                    seenCardUIDs.add(relatedCardUID);

                    const columnElement = getColumnElement(relatedCard.project_column_uid);
                    const columnRect = columnElement?.getBoundingClientRect();
                    const clip = clipForColumn(relatedCard.project_column_uid);
                    const candidates = getCardElements(relatedCardUID);
                    const targetElement =
                        candidates.find((element) => clip && intersectRelationshipRects(element.getBoundingClientRect(), clip)) ?? candidates[0];
                    const targetRect = targetElement?.getBoundingClientRect();
                    const visibleTarget = targetRect && clip && intersectRelationshipRects(targetRect, clip);
                    const targetColumn = columnsMap.get(relatedCard.project_column_uid);
                    const label = sourceIsParent ? relationshipType.child_name : relationshipType.parent_name;
                    let virtualDirection: "up" | "down" | undefined;
                    if (!targetElement) {
                        // The column owns filtering, hierarchy, and virtualization.
                        document.dispatchEvent(
                            new CustomEvent<IBoardCardLocationEventDetail>(BOARD_CARD_LOCATION_EVENT, {
                                detail: {
                                    cardUID: relatedCardUID,
                                    columnUID: relatedCard.project_column_uid,
                                    onLocated: (positions, scrollOffset) => {
                                        if (positions.length) virtualDirection = positions.every((offset) => offset < scrollOffset) ? "up" : "down";
                                    },
                                },
                            })
                        );
                        if (!virtualDirection) return;
                    }

                    if (visibleTarget) {
                        if (relatedCard.project_column_uid === sourceCard.project_column_uid) return;
                        const source = { x: sourceIsParent ? sourceRect.right : sourceRect.left, y: sourceY };
                        const target = {
                            x: sourceIsParent ? visibleTarget.left : visibleTarget.right,
                            y: (visibleTarget.top + visibleTarget.bottom) / 2,
                        };
                        edges.push({
                            uid: relationship.uid,
                            label,
                            path: relationshipCurve(source, target, sourceIsParent),
                            labelX: (source.x + target.x) / 2,
                            labelY: (source.y + target.y) / 2 - 6,
                        });
                        return;
                    }

                    let side = columnRect && getRelationshipDirection(columnRect, viewport);
                    if (!side && targetRect && clip) side = getRelationshipDirection(targetRect, clip);
                    side ??= virtualDirection;
                    if (!side) return;
                    const targets = previewGroups.get(side) ?? [];
                    targets.push({
                        columnUID: relatedCard.project_column_uid,
                        cardUID: relatedCardUID,
                        title: relatedCard.title,
                        columnName: targetColumn?.name ?? "",
                        label,
                        sourceIsParent,
                        relationshipUID: relationship.uid,
                    });
                    previewGroups.set(side, targets);
                });

                const previews = [...previewGroups].map(([side, targets]) => {
                    const width = Math.min(224, (viewport.right - viewport.left) / 2 - 16);
                    const height = Math.min(targets.length * 52, 176, (viewport.bottom - viewport.top) / 2 - 16);
                    const left =
                        side === "left"
                            ? viewport.left + 12
                            : side === "right"
                              ? viewport.right - width - 12
                              : (viewport.left + viewport.right - width) / 2;
                    const top =
                        side === "up"
                            ? viewport.top + 12
                            : side === "down"
                              ? viewport.bottom - height - 12
                              : Math.max(viewport.top + 12, Math.min(sourceY - height / 2, viewport.bottom - height - 12));
                    targets.forEach((target) => {
                        const source = { x: target.sourceIsParent ? sourceRect.right : sourceRect.left, y: sourceY };
                        const endpoint = {
                            x: side === "left" ? left + width : side === "right" ? left : left + width / 2,
                            y: side === "up" ? top + height : side === "down" ? top : top + height / 2,
                        };
                        edges.push({
                            uid: target.relationshipUID,
                            label: "",
                            path: relationshipCurve(source, endpoint, target.sourceIsParent),
                            labelX: 0,
                            labelY: 0,
                        });
                    });
                    return { side, targets, left, top, width, height };
                });
                setLayout({ edges, previews });
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
    }, [cardsMap, columnsMap, hoveredCardUID, hoveredElement, scrollableRef, filters]);

    const focusPreview = (preview: IPreviewTarget, focus: boolean) => {
        keepOpen();
        const columnElement = document.querySelector<HTMLElement>(`[${BOARD_COLUMN_TOUCH_DND_ATTR}="${CSS.escape(preview.columnUID)}"]`);
        const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
        columnElement?.scrollIntoView({ behavior, block: "nearest", inline: "center" });
        document.dispatchEvent(
            new CustomEvent<IBoardCardFocusEventDetail>(BOARD_CARD_FOCUS_EVENT, {
                detail: { cardUID: preview.cardUID, columnUID: preview.columnUID, focus },
            })
        );
        setHoveredElement(null);
    };

    if (!hoveredCardUID || (!layout.edges.length && !layout.previews.length)) {
        return null;
    }

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
            {layout.previews.map((preview) => (
                <div
                    key={preview.side}
                    {...{ [RELATIONSHIP_PREVIEW_ATTR]: preview.side }}
                    className="fixed z-40 overflow-y-auto rounded-lg border border-primary/30 bg-secondary shadow-lg"
                    style={{ left: preview.left, top: preview.top, width: preview.width, maxHeight: preview.height }}
                    onPointerEnter={keepOpen}
                    onPointerLeave={scheduleClose}
                    onFocusCapture={keepOpen}
                    onBlurCapture={(event) => {
                        if (!event.currentTarget.contains(event.relatedTarget)) scheduleClose();
                    }}
                >
                    {preview.targets.map((target) => (
                        <Button
                            key={target.cardUID}
                            type="button"
                            variant="ghost"
                            className="h-auto w-full justify-start gap-2 whitespace-normal px-3 py-2 text-left"
                            aria-label={`${target.title} · ${target.columnName} · ${target.label}`}
                            onClick={(event) => focusPreview(target, event.detail === 0)}
                        >
                            <IconComponent icon={`arrow-${preview.side}`} size="4" className="shrink-0" />
                            <span className="min-w-0">
                                <span className="block truncate text-xs font-semibold">{target.title}</span>
                                <span className="block truncate text-[10px] text-muted-foreground">
                                    {target.columnName} · {target.label}
                                </span>
                            </span>
                        </Button>
                    ))}
                </div>
            ))}
        </>,
        document.body
    );
});
BoardCardRelationshipOverlay.displayName = "Board.CardRelationshipOverlay";

export default BoardCardRelationshipOverlay;
