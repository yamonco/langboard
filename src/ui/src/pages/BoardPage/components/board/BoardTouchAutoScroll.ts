const DEFAULT_EDGE_PX = 72;
const DEFAULT_MAX_STEP_PX = 18;

export function boardTouchAutoScrollDelta(
    pointerX: number,
    viewportLeft: number,
    viewportRight: number,
    edgeSize = DEFAULT_EDGE_PX,
    maxStep = DEFAULT_MAX_STEP_PX
): number {
    if (viewportRight <= viewportLeft || edgeSize <= 0 || maxStep <= 0) return 0;

    const leftDepth = Math.max(0, Math.min(1, (viewportLeft + edgeSize - pointerX) / edgeSize));
    if (leftDepth > 0) return -maxStep * leftDepth * leftDepth;

    const rightDepth = Math.max(0, Math.min(1, (pointerX - (viewportRight - edgeSize)) / edgeSize));
    return rightDepth > 0 ? maxStep * rightDepth * rightDepth : 0;
}

export function startBoardTouchAutoScroll(scrollable: HTMLElement, getPointerX: () => number): () => void {
    let frame = 0;
    const tick = () => {
        const viewport = scrollable.getBoundingClientRect();
        const left = boardTouchAutoScrollDelta(getPointerX(), viewport.left, viewport.right);
        if (left !== 0) scrollable.scrollBy({ left, behavior: "auto" });
        frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
}
