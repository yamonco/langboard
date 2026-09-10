import { parseProjectActivityTimestamp } from "../../../core/models/projectActivityTimestamp.ts";

export interface IProjectActivityPriority {
    uid: string;
    title: string;
    starred: boolean;
    created_at: Date;
    last_activity_at: Date | null;
    related_to_current_user?: boolean;
    related_activity_at?: Date | null;
}

export type TProjectActivityKind = "project" | "related";

export function projectActivityAt(project: IProjectActivityPriority, kind: TProjectActivityKind): Date {
    const projectActivity = project.last_activity_at ?? project.created_at;
    return kind === "related" ? (project.related_activity_at ?? projectActivity) : projectActivity;
}

export function compareProjectRelatedActivity(a: IProjectActivityPriority, b: IProjectActivityPriority): number {
    const aRelated = a.related_activity_at?.getTime() ?? Number.NEGATIVE_INFINITY;
    const bRelated = b.related_activity_at?.getTime() ?? Number.NEGATIVE_INFINITY;
    return bRelated - aRelated || compareProjectActivityPriority(a, b);
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
    const recordedAt = parseProjectActivityTimestamp(candidate);
    if (!recordedAt || (current && recordedAt <= current)) {
        return current;
    }
    return recordedAt;
}
