export interface IProjectActivityPriority {
    uid: string;
    title: string;
    starred: boolean;
    created_at: Date;
    last_activity_at: Date | null;
    related_to_current_user?: boolean;
}

export function compareProjectActivityPriority(a: IProjectActivityPriority, b: IProjectActivityPriority): number {
    if (a.starred !== b.starred) {
        return a.starred ? -1 : 1;
    }

    const aActivity = (a.last_activity_at ?? a.created_at).getTime();
    const bActivity = (b.last_activity_at ?? b.created_at).getTime();
    if (aActivity !== bActivity) {
        return bActivity - aActivity;
    }

    const titleOrder = a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    return titleOrder || a.uid.localeCompare(b.uid);
}

export function newerProjectActivity(current: Date | null, candidate: string): Date | null {
    const recordedAt = new Date(candidate);
    if (Number.isNaN(recordedAt.getTime()) || (current && recordedAt <= current)) {
        return current;
    }
    return recordedAt;
}
