import { type RefObject, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { dropTargetForElements } from "@atlaskit/pragmatic-drag-and-drop/element/adapter";
import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";
import { BOARD_COLUMN_TOUCH_DND_ATTR } from "@/pages/BoardPage/components/board/BoardConstants";
import { MINIMAP_WIDTH, minimapColumnPath, minimapScrollAt, minimapViewport } from "@/pages/BoardPage/components/board/BoardMinimapLayout";

export default function BoardMinimap({ scrollableRef, scrollportId }: { scrollableRef: RefObject<HTMLDivElement | null>; scrollportId: string }) {
    const [t] = useTranslation();
    const [opened, setOpened] = useState(true);
    const [metrics, setMetrics] = useState({ content: 0, viewport: 0, step: 320, path: "" });
    const [left, setLeft] = useState(0);
    const drag = useRef<{ x: number; left: number } | null>(null);
    const root = useRef<HTMLDivElement>(null);
    const marker = minimapViewport(metrics.content, metrics.viewport, left);

    useEffect(() => {
        const scrollable = scrollableRef.current;
        if (!scrollable) return;
        let frame = 0;
        const measure = () => {
            const origin = scrollable.getBoundingClientRect().left - scrollable.scrollLeft;
            const columns = [...scrollable.querySelectorAll<HTMLElement>(`[${BOARD_COLUMN_TOUCH_DND_ATTR}]`)].map((column) => {
                const rect = column.getBoundingClientRect();
                return { left: rect.left - origin, width: rect.width };
            });
            setMetrics({
                content: scrollable.scrollWidth,
                viewport: scrollable.clientWidth,
                step: columns.length > 1 ? columns[1].left - columns[0].left : (columns[0]?.width ?? scrollable.clientWidth),
                path: minimapColumnPath(columns, scrollable.scrollWidth),
            });
            setLeft(scrollable.scrollLeft);
        };
        const scrolled = () => {
            if (!frame)
                frame = requestAnimationFrame(() => {
                    frame = 0;
                    setLeft(scrollable.scrollLeft);
                });
        };
        const observer = new ResizeObserver(measure);
        observer.observe(scrollable);
        if (scrollable.firstElementChild) observer.observe(scrollable.firstElementChild);
        scrollable.addEventListener("scroll", scrolled, { passive: true });
        measure();
        return () => {
            observer.disconnect();
            scrollable.removeEventListener("scroll", scrolled);
            cancelAnimationFrame(frame);
        };
    }, [scrollableRef]);

    useEffect(() => {
        if (!root.current || !marker.maximum) return;
        // Navigation is not a card/column drop destination. Block sticky targets behind the widget.
        return dropTargetForElements({ element: root.current, getData: () => ({ type: "board-minimap-navigation" }) });
    }, [marker.maximum]);

    if (marker.maximum <= 1) return null;
    const scroll = (value: number) => scrollableRef.current?.scrollTo({ left: Math.max(0, Math.min(marker.maximum, value)), behavior: "instant" });

    return (
        <div
            ref={root}
            className={cn(
                "fixed bottom-20 right-4 z-30 w-56 max-w-[calc(100vw-2rem)] overflow-hidden rounded-xl",
                "border bg-background/95 shadow-lg backdrop-blur"
            )}
            data-board-minimap=""
        >
            <div className="flex items-center">
                <Button
                    variant="ghost"
                    className="h-11 min-w-0 flex-1 justify-between rounded-none px-2 text-xs md:h-8"
                    aria-expanded={opened}
                    onClick={() => setOpened(!opened)}
                >
                    <span className="flex items-center gap-1.5">
                        <IconComponent icon="map" size="3.5" />
                        {t("board.Minimap")}
                    </span>
                    <IconComponent icon={opened ? "chevron-down" : "chevron-up"} size="3.5" />
                </Button>
                <Button
                    variant="ghost"
                    className="size-11 shrink-0 rounded-none p-0 md:size-8"
                    aria-label={t("board.Previous column")}
                    disabled={left <= 1}
                    onClick={() => scroll(left - metrics.step)}
                >
                    <IconComponent icon="chevron-left" size="4" />
                </Button>
                <Button
                    variant="ghost"
                    className="size-11 shrink-0 rounded-none p-0 md:size-8"
                    aria-label={t("board.Next column")}
                    disabled={left >= marker.maximum - 1}
                    onClick={() => scroll(left + metrics.step)}
                >
                    <IconComponent icon="chevron-right" size="4" />
                </Button>
            </div>
            {opened && (
                <svg
                    viewBox={`0 0 ${MINIMAP_WIDTH} 48`}
                    className={cn(
                        "block h-12 w-full cursor-ew-resize touch-none outline-none",
                        "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    )}
                    role="scrollbar"
                    tabIndex={0}
                    aria-label={t("board.Scroll board horizontally")}
                    aria-orientation="horizontal"
                    aria-controls={scrollportId}
                    aria-valuemin={0}
                    aria-valuemax={Math.round(marker.maximum)}
                    aria-valuenow={Math.round(Math.max(0, Math.min(left, marker.maximum)))}
                    onPointerDown={(event) => {
                        if (event.button !== 0) return;
                        const viewport = scrollableRef.current;
                        if (!viewport) return;
                        event.preventDefault();
                        event.currentTarget.focus();
                        event.currentTarget.setPointerCapture(event.pointerId);
                        const rect = event.currentTarget.getBoundingClientRect();
                        const x = ((event.clientX - rect.left) / rect.width) * MINIMAP_WIDTH;
                        if (x < marker.x || x > marker.x + marker.width)
                            scroll(minimapScrollAt(x / MINIMAP_WIDTH, metrics.content, metrics.viewport));
                        drag.current = { x: event.clientX, left: viewport.scrollLeft };
                    }}
                    onPointerMove={(event) => {
                        if (drag.current)
                            scroll(
                                drag.current.left +
                                    ((event.clientX - drag.current.x) / event.currentTarget.getBoundingClientRect().width) * metrics.content
                            );
                    }}
                    onPointerUp={() => {
                        drag.current = null;
                    }}
                    onPointerCancel={() => {
                        drag.current = null;
                    }}
                    onLostPointerCapture={() => {
                        drag.current = null;
                    }}
                    onKeyDown={(event) => {
                        const steps: Record<string, number> = {
                            ArrowLeft: -metrics.viewport * 0.15,
                            ArrowRight: metrics.viewport * 0.15,
                            PageUp: -metrics.viewport,
                            PageDown: metrics.viewport,
                        };
                        if (event.key === "Home" || event.key === "End" || Object.hasOwn(steps, event.key)) {
                            event.preventDefault();
                            scroll(event.key === "Home" ? 0 : event.key === "End" ? marker.maximum : left + steps[event.key]);
                        }
                    }}
                >
                    <path d={metrics.path} className="fill-muted-foreground/30" />
                    <rect x={marker.x} y={3} width={marker.width} height={42} rx={3} className="fill-primary/20 stroke-primary" strokeWidth={2} />
                </svg>
            )}
        </div>
    );
}
