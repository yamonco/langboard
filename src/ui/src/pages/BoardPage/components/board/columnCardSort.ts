export const COLUMN_CARD_SORT_MODES = [
    "manual",
    "created_newest",
    "created_oldest",
    "updated_newest",
    "updated_oldest",
    "deadline",
    "unassigned",
] as const;
export type TColumnCardSort = (typeof COLUMN_CARD_SORT_MODES)[number];
interface ISortableCard {
    uid: string;
    order: number;
    created_at: Date;
    updated_at: Date;
    deadline_at?: Date;
    member_uids?: string[];
}
export function sortColumnCards<T extends ISortableCard>(cards: readonly T[], mode: TColumnCardSort): T[] {
    const time = (date?: Date) => date?.getTime() ?? Infinity;
    return [...cards].sort((a, b) => {
        let result = 0;
        switch (mode) {
            case "created_newest":
                result = time(b.created_at) - time(a.created_at);
                break;
            case "created_oldest":
                result = time(a.created_at) - time(b.created_at);
                break;
            case "updated_newest":
                result = time(b.updated_at) - time(a.updated_at);
                break;
            case "updated_oldest":
                result = time(a.updated_at) - time(b.updated_at);
                break;
            case "deadline":
                result = time(a.deadline_at) - time(b.deadline_at);
                break;
            case "unassigned":
                result = Number(!!a.member_uids?.length) - Number(!!b.member_uids?.length);
                break;
        }
        return (Number.isNaN(result) ? 0 : result) || a.order - b.order || a.uid.localeCompare(b.uid);
    });
}
