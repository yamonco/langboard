import type { IDescriptionChunk } from "./descriptionChunks";

export const MAX_RAIL_MARKERS = 96;

export interface IRailMarker {
    index: number;
    chunk: IDescriptionChunk;
    rangeLabel?: string;
}

export function buildRailMarkers(chunks: IDescriptionChunk[]): IRailMarker[] {
    if (chunks.length <= MAX_RAIL_MARKERS) {
        return chunks.map((chunk, index) => ({ index, chunk }));
    }

    const bucketSize = Math.ceil(chunks.length / MAX_RAIL_MARKERS);
    const markers: IRailMarker[] = [];

    for (let start = 0; start < chunks.length; start += bucketSize) {
        const end = Math.min(chunks.length, start + bucketSize);
        const bucket = chunks.slice(start, end);
        const headingOffset = bucket.findIndex((chunk) => Boolean(chunk.metadata.heading));
        const representativeIndex = start + (headingOffset >= 0 ? headingOffset : 0);

        markers.push({
            index: representativeIndex,
            chunk: chunks[representativeIndex],
            rangeLabel: `${start + 1}-${end}`,
        });
    }

    return markers;
}

export function getNearestMarkerIndex(markers: IRailMarker[], activeIndex: number): number {
    if (!markers.length) {
        return -1;
    }

    let nearest = 0;
    let shortestDistance = Number.MAX_SAFE_INTEGER;
    markers.forEach((marker, markerIndex) => {
        const distance = Math.abs(marker.index - activeIndex);
        if (distance < shortestDistance) {
            nearest = markerIndex;
            shortestDistance = distance;
        }
    });

    return nearest;
}

export function getMarkerWidth(distance: number): string {
    if (distance === 0) {
        return "w-5";
    }
    if (distance === 1) {
        return "w-4";
    }
    if (distance === 2) {
        return "w-3";
    }
    if (distance === 3) {
        return "w-2";
    }

    return "w-1.5";
}

export function getMarkerOpacity(distance: number): string {
    if (distance === 0) {
        return "opacity-100";
    }
    if (distance <= 2) {
        return "opacity-70";
    }
    if (distance <= 5) {
        return "opacity-50";
    }

    return "opacity-30";
}
