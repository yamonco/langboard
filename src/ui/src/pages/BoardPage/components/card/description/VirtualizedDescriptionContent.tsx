import { useVirtualizer } from "@tanstack/react-virtual";
import Box from "@/components/base/Box";
import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { AuthUser, ProjectCard } from "@/core/models";
import type { TUserLikeModel } from "@/core/models/ModelRegistry";
import { BoardCardDescriptionStaticChunk } from "./BoardCardDescriptionStaticChunk";
import type { IDescriptionChunk } from "./descriptionChunks";
import { DescriptionOverviewRail } from "./DescriptionOverviewRail";

interface IVirtualizedDescriptionContentProps {
    chunks: IDescriptionChunk[];
    currentUser: AuthUser.TModel;
    mentionables: TUserLikeModel[];
    cards: ProjectCard.TModel[];
    projectUID: string;
    cardUID: string;
    scrollParentRef: React.RefObject<HTMLDivElement | null>;
}

function estimateChunkHeight(chunk: IDescriptionChunk): number {
    if (chunk.metadata.type === "table" || chunk.metadata.type === "code") {
        return 280;
    }
    if (chunk.metadata.isHeavy) {
        return 240;
    }
    if (chunk.metadata.type === "heading") {
        return 72;
    }

    return Math.min(260, Math.max(96, 96 + chunk.metadata.textLength * 0.05));
}

export const VirtualizedDescriptionContent = memo(
    ({ chunks, currentUser, mentionables, cards, projectUID, cardUID, scrollParentRef }: IVirtualizedDescriptionContentProps): React.JSX.Element => {
        const containerRef = useRef<HTMLDivElement | null>(null);
        const [scrollMargin, setScrollMargin] = useState(0);
        const [activeIndex, setActiveIndex] = useState(0);

        const measureScrollMargin = useCallback(() => {
            const scrollElement = scrollParentRef.current;
            const container = containerRef.current;
            if (!scrollElement || !container) {
                return;
            }

            const scrollRect = scrollElement.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            const next = containerRect.top - scrollRect.top + scrollElement.scrollTop;
            setScrollMargin((previous) => (Math.abs(previous - next) < 1 ? previous : next));
        }, [scrollParentRef]);

        useLayoutEffect(() => {
            measureScrollMargin();
        }, [measureScrollMargin, chunks.length]);

        useEffect(() => {
            const scrollElement = scrollParentRef.current;
            const container = containerRef.current;
            if (!scrollElement || !container) {
                return;
            }

            let frame = 0;
            const scheduleMeasure = () => {
                cancelAnimationFrame(frame);
                frame = requestAnimationFrame(measureScrollMargin);
            };

            const observer = new ResizeObserver(scheduleMeasure);
            observer.observe(scrollElement);
            observer.observe(container);
            window.addEventListener("resize", scheduleMeasure);

            return () => {
                cancelAnimationFrame(frame);
                observer.disconnect();
                window.removeEventListener("resize", scheduleMeasure);
            };
        }, [measureScrollMargin, scrollParentRef]);

        const virtualizer = useVirtualizer({
            count: chunks.length,
            getScrollElement: () => scrollParentRef.current,
            estimateSize: (index) => estimateChunkHeight(chunks[index]),
            measureElement: (element) => element.getBoundingClientRect().height,
            overscan: 4,
            scrollMargin,
            onChange: (instance) => {
                const items = instance.getVirtualItems();
                if (!items.length) {
                    return;
                }

                const viewportTop = (instance.scrollOffset ?? 0) + 8;
                let nextIndex = items[0].index;
                for (const item of items) {
                    if (item.start <= viewportTop) {
                        nextIndex = item.index;
                        continue;
                    }

                    break;
                }

                setActiveIndex((previous) => (previous === nextIndex ? previous : nextIndex));
            },
        });

        const scrollToChunk = useCallback(
            (index: number) => {
                virtualizer.scrollToIndex(index, { align: "start", behavior: "auto" });
                requestAnimationFrame(() => {
                    virtualizer.scrollToIndex(index, { align: "start", behavior: "auto" });
                });
            },
            [virtualizer]
        );

        return (
            <Box ref={containerRef} position="relative" className="pr-7">
                <Box position="relative" style={{ height: `${virtualizer.getTotalSize()}px` }}>
                    {virtualizer.getVirtualItems().map((virtualItem) => {
                        const chunk = chunks[virtualItem.index];
                        if (!chunk) {
                            return null;
                        }

                        return (
                            <Box
                                key={virtualItem.key}
                                data-index={virtualItem.index}
                                ref={(node) => {
                                    virtualizer.measureElement(node);
                                }}
                                position="absolute"
                                top="0"
                                left="0"
                                w="full"
                                className="pb-2"
                                style={{
                                    transform: `translateY(${virtualItem.start - scrollMargin}px)`,
                                }}
                            >
                                <BoardCardDescriptionStaticChunk
                                    chunk={chunk}
                                    currentUser={currentUser}
                                    mentionables={mentionables}
                                    cards={cards}
                                    projectUID={projectUID}
                                    cardUID={cardUID}
                                />
                            </Box>
                        );
                    })}
                </Box>

                {chunks.length > 1 && <DescriptionOverviewRail chunks={chunks} activeIndex={activeIndex} onNavigate={scrollToChunk} />}
            </Box>
        );
    }
);

export default VirtualizedDescriptionContent;
