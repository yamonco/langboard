import { parseProjectActivityTimestamp } from "../../../core/models/projectActivityTimestamp.ts";

export interface IProjectActivityPriority {
    uid: string;
    title: string;
    starred: boolean;
    created_at: Date;
    last_viewed_at: Date;
    view_count: number;
    last_activity_at: Date | null;
    related_to_current_user?: boolean;
    related_activity_at?: Date | null;
}

export type TProjectActivityKind = "project" | "related";

const DAY_MS = 24 * 60 * 60 * 1000;
const RECENCY_HALF_LIFE_DAYS = 30;

const recencySignal = (value: Date | null | undefined, now: number): number => {
    if (!value) return 0;
    const ageDays = Math.max(0, now - value.getTime()) / DAY_MS;
    return 2 ** (-ageDays / RECENCY_HALF_LIFE_DAYS);
};

export function projectPriorityScore(project: IProjectActivityPriority, now = Date.now()): number {
    const activityAt = project.last_activity_at ?? project.created_at;
    const frequencySignal = 1 - Math.exp(-Math.max(0, project.view_count) / 20);
    return (
        recencySignal(project.last_viewed_at, now) * 0.4 +
        recencySignal(activityAt, now) * 0.35 +
        recencySignal(project.related_activity_at, now) * 0.15 +
        frequencySignal * 0.1
    );
}

export function projectActivityAt(project: IProjectActivityPriority, kind: TProjectActivityKind): Date {
    const projectActivity = project.last_activity_at ?? project.created_at;
    return kind === "related" ? (project.related_activity_at ?? projectActivity) : projectActivity;
}

export function compareProjectRelatedActivity(a: IProjectActivityPriority, b: IProjectActivityPriority): number {
    const aRelated = a.related_activity_at?.getTime() ?? Number.NEGATIVE_INFINITY;
    const bRelated = b.related_activity_at?.getTime() ?? Number.NEGATIVE_INFINITY;
    return bRelated - aRelated || compareProjectActivityPriority(a, b);
}

export function compareProjectActivityPriority(a: IProjectActivityPriority, b: IProjectActivityPriority, now = Date.now()): number {
    if (a.starred !== b.starred) {
        return a.starred ? -1 : 1;
    }

    const scoreOrder = projectPriorityScore(b, now) - projectPriorityScore(a, now);
    if (scoreOrder !== 0) {
        return scoreOrder;
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
