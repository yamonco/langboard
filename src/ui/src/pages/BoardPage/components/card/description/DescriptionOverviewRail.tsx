import Box from "@/components/base/Box";
import HoverCard from "@/components/base/HoverCard";
import { cn } from "@/core/utils/ComponentUtils";
import { useTranslation } from "react-i18next";
import { memo, useMemo } from "react";

import type { IDescriptionChunk } from "./descriptionChunks";
import { buildRailMarkers, getMarkerOpacity, getMarkerWidth, getNearestMarkerIndex } from "./descriptionOverviewRailData";

interface IDescriptionOverviewRailProps {
    chunks: IDescriptionChunk[];
    activeIndex: number;
    onNavigate: (index: number) => void;
}

export function getPreviewTitleKey(type: IDescriptionChunk["metadata"]["type"]): string {
    switch (type) {
        case "code":
            return "editor.Code";
        case "table":
            return "editor.Table";
        case "list":
            return "editor.Lists";
        case "quote":
            return "editor.Quote";
        case "media":
            return "editor.Image";
        case "mixed":
            return "editor.Text";
        default:
            return "editor.Paragraph";
    }
}

export const DescriptionOverviewRail = memo(({ chunks, activeIndex, onNavigate }: IDescriptionOverviewRailProps): React.JSX.Element => {
    const [t] = useTranslation();
    const markers = useMemo(() => buildRailMarkers(chunks), [chunks]);
    const nearestActiveMarkerIndex = useMemo(() => getNearestMarkerIndex(markers, activeIndex), [activeIndex, markers]);

    return (
        <Box position="absolute" right="0" top="2" bottom="2" className="pointer-events-none hidden w-7 justify-center md:flex" aria-hidden={false}>
            <Box className="pointer-events-auto flex max-h-full flex-col items-end justify-center gap-[3px] py-2">
                {markers.map((marker, markerIndex) => {
                    const distance = Math.abs(markerIndex - nearestActiveMarkerIndex);
                    const active = distance === 0;

                    return (
                        <HoverCard.Root key={`${marker.chunk.id}-${marker.index}`} openDelay={180} closeDelay={80}>
                            <HoverCard.Trigger asChild>
                                <button
                                    type="button"
                                    aria-label={t("editor.Navigate description", { position: marker.index + 1, total: chunks.length })}
                                    aria-current={active ? "location" : undefined}
                                    className={cn(
                                        "h-[3px] shrink-0 rounded-full bg-muted-foreground/70",
                                        "transition-[width,opacity,transform] duration-150 ease-out",
                                        "hover:scale-x-110 hover:bg-foreground hover:opacity-100",
                                        "focus-visible:bg-foreground focus-visible:outline-none",
                                        "focus-visible:ring-2 focus-visible:ring-ring",
                                        "motion-reduce:transition-none",
                                        getMarkerWidth(distance),
                                        getMarkerOpacity(distance),
                                        active && "bg-foreground"
                                    )}
                                    onPointerDown={(event) => event.stopPropagation()}
                                    onClick={(event) => {
                                        event.stopPropagation();
                                        onNavigate(marker.index);
                                    }}
                                />
                            </HoverCard.Trigger>

                            <HoverCard.Portal>
                                <HoverCard.Content
                                    side="left"
                                    align="center"
                                    sideOffset={10}
                                    className="w-72"
                                    onPointerDown={(event) => event.stopPropagation()}
                                >
                                    <div className="truncate text-sm font-semibold">
                                        {marker.chunk.metadata.heading || t(getPreviewTitleKey(marker.chunk.metadata.type))}
                                    </div>
                                    {!!marker.chunk.metadata.previewText && (
                                        <div className="mt-1 line-clamp-3 text-xs leading-5 text-muted-foreground">
                                            {marker.chunk.metadata.previewText}
                                        </div>
                                    )}
                                    <div className="mt-2 text-[11px] text-muted-foreground/80">
                                        {marker.rangeLabel ?? `${marker.index + 1} / ${chunks.length}`}
                                    </div>
                                </HoverCard.Content>
                            </HoverCard.Portal>
                        </HoverCard.Root>
                    );
                })}
            </Box>
        </Box>
    );
});

export default DescriptionOverviewRail;
