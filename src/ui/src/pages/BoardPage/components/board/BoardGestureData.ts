export const BOARD_MEMBER_DRAG_TYPE = "board-member";

export function draggedBoardMember(data: Record<string | symbol, unknown>, projectUID: string): string | undefined {
    return data.type === BOARD_MEMBER_DRAG_TYPE && data.projectUID === projectUID && typeof data.memberUID === "string" && data.memberUID
        ? data.memberUID
        : undefined;
}

export function draggedBoardCard(data: Record<string | symbol, unknown>, rowSymbol: symbol, projectUID: string): string | undefined {
    const row = data.row;
    if (!data[rowSymbol] || !row || typeof row !== "object") return;
    if (!("uid" in row) || typeof row.uid !== "string" || !("project_uid" in row) || row.project_uid !== projectUID) return;
    return row.uid || undefined;
}

export function nextCardOrder(cards: readonly { project_column_uid: string; order: number }[], columnUID: string): number {
    return cards.filter((card) => card.project_column_uid === columnUID).reduce((last, card) => Math.max(last, card.order + 1), 0);
}
