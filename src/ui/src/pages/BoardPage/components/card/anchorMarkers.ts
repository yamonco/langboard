import type { IAnchorMarkerPosition } from "./BoardCardDescription";

export function areAnchorMarkersEqual(previous: IAnchorMarkerPosition[], next: IAnchorMarkerPosition[]): boolean {
    if (previous === next || previous.length !== next.length) {
        return previous === next;
    }

    return previous.every((marker, index) => {
        const nextMarker = next[index];
        return (
            marker.commentUID === nextMarker.commentUID &&
            marker.quote === nextMarker.quote &&
            marker.commentPreview === nextMarker.commentPreview &&
            Math.abs(marker.top - nextMarker.top) < 0.5
        );
    });
}
