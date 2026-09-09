export const MINIMAP_WIDTH = 224;

export function minimapViewport(content: number, viewport: number, scroll: number) {
    const maximum = Math.max(0, content - viewport);
    const width = content > 0 ? Math.min(MINIMAP_WIDTH, Math.max(8, (viewport / content) * MINIMAP_WIDTH)) : MINIMAP_WIDTH;
    return { x: maximum ? (Math.max(0, Math.min(scroll, maximum)) / maximum) * (MINIMAP_WIDTH - width) : 0, width, maximum };
}

export function minimapScrollAt(position: number, content: number, viewport: number): number {
    return Math.max(0, Math.min(content - viewport, position * content - viewport / 2));
}

/** One SVG path with at most 112 bands, even when a board has thousands of columns. */
export function minimapColumnPath(columns: readonly { left: number; width: number }[], content: number): string {
    if (content <= 0) return "";
    const bands = new Set<number>();
    return columns
        .flatMap((column) => {
            const x = Math.max(0, Math.min(MINIMAP_WIDTH - 1, (column.left / content) * MINIMAP_WIDTH));
            const band = Math.floor(x / 2);
            if (bands.has(band)) return [];
            bands.add(band);
            const width = Math.min(MINIMAP_WIDTH - x, Math.max(1, (column.width / content) * MINIMAP_WIDTH - 1));
            return [`M${x.toFixed(2)} 6h${width.toFixed(2)}v36h-${width.toFixed(2)}z`];
        })
        .join(" ");
}
