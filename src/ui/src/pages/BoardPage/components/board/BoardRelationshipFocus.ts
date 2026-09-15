/** Bridge the card's title and its portaled preview; leave interior tabbing native. */
export function relationshipFocusAction(
    key: string,
    shiftKey: boolean,
    sourceFocused: boolean,
    previewIndex: number,
    previewCount: number
): "first" | "source" | "next" | "dismiss" | undefined {
    if (key === "Escape" && (sourceFocused || previewIndex >= 0)) return "dismiss";
    if (key !== "Tab" || !previewCount) return;
    if (sourceFocused && !shiftKey) return "first";
    if (previewIndex === 0 && shiftKey) return "source";
    if (previewIndex === previewCount - 1 && !shiftKey) return "next";
}
