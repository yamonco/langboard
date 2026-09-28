export interface IBoardCardChecklistProgress {
    completed: number;
    total: number;
    ratio: number;
}

export type TDeadlinePressureLevel = "none" | "near" | "due-soon" | "critical" | "overdue";

export const DEADLINE_PRESSURE_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

export const calculateChecklistProgress = (checkitems: ReadonlyArray<{ is_checked?: boolean | null }>): IBoardCardChecklistProgress => {
    const completed = checkitems.filter((checkitem) => checkitem.is_checked).length;
    const total = checkitems.length;

    return {
        completed,
        total,
        ratio: total ? Math.min(1, completed / total) : 0,
    };
};

export const calculateChecklistProgressFromCounts = (completedCount = 0, totalCount = 0): IBoardCardChecklistProgress => {
    const total = Math.max(0, totalCount);
    const completed = Math.min(total, Math.max(0, completedCount));
    return { completed, total, ratio: total ? completed / total : 0 };
};

export const getChecklistBorderDashes = (completed: number, total: number, perimeter: number) => {
    const count = Math.max(0, Math.floor(total));
    const done = Math.min(count, Math.max(0, Math.floor(completed)));
    const gap = count > 1 && perimeter > 0 ? Math.min(0.25, (6 * count) / perimeter) : 0;
    const segment = 1 - gap;
    return {
        track: `${segment} ${gap}`,
        value: Array.from({ length: done }, (_, index) => (index === done - 1 ? `${segment} ${count - done + gap}` : `${segment} ${gap}`)).join(" "),
    };
};

/**
 * Terminated-state predicate: a card counts as finished work only when it has
 * at least one checklist item and every item is completed.
 */
export const isChecklistCompleted = (progress: Pick<IBoardCardChecklistProgress, "completed" | "total">): boolean =>
    progress.total > 0 && progress.completed === progress.total;

export const isDeadlineFinished = ({
    archivedAt,
    checklist,
}: {
    archivedAt?: Date | null;
    checklist: Pick<IBoardCardChecklistProgress, "completed" | "total">;
}): boolean => Boolean(archivedAt) || isChecklistCompleted(checklist);

export const getDeadlineCalendarDays = ({ deadlineAt, now }: { deadlineAt: Date; now: Date }): number => {
    // Compare local calendar dates, not elapsed 24-hour periods (DST can make those differ).
    const deadlineDay = Date.UTC(deadlineAt.getFullYear(), deadlineAt.getMonth(), deadlineAt.getDate());
    const currentDay = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((deadlineDay - currentDay) / (24 * 60 * 60 * 1000));
};

export const getOverdueDays = ({ deadlineAt, now }: { deadlineAt?: Date | null; now: Date }): number => {
    if (!deadlineAt || deadlineAt.getTime() >= now.getTime()) return 0;
    return Math.max(0, -getDeadlineCalendarDays({ deadlineAt, now }));
};

export const getUpcomingDeadlineDays = ({ deadlineAt, now, isCompleted = false }: { deadlineAt?: Date | null; now: Date; isCompleted?: boolean }): number | null => {
    if (!deadlineAt || isCompleted || deadlineAt.getTime() <= now.getTime()) return null;
    const days = getDeadlineCalendarDays({ deadlineAt, now });
    return days >= 0 && days <= 3 ? days : null;
};

export const calculateDeadlinePressure = ({
    deadlineAt,
    isCompleted = false,
    now,
}: {
    deadlineAt?: Date | null;
    isCompleted?: boolean;
    now: Date;
}): number => {
    if (!deadlineAt || isCompleted) {
        return 0;
    }

    const remainingMs = deadlineAt.getTime() - now.getTime();
    if (remainingMs <= 0) {
        return 1;
    }

    return Math.min(1, 1 - remainingMs / DEADLINE_PRESSURE_WINDOW_MS);
};

export const getDeadlinePressureLevel = ({
    deadlineAt,
    isCompleted = false,
    now,
}: {
    deadlineAt?: Date | null;
    isCompleted?: boolean;
    now: Date;
}): TDeadlinePressureLevel => {
    const remainingDays = deadlineAt ? (deadlineAt.getTime() - now.getTime()) / (24 * 60 * 60 * 1000) : Number.POSITIVE_INFINITY;

    if (!deadlineAt || isCompleted || remainingDays > 3) {
        return "none";
    }
    if (remainingDays <= 0) {
        return "overdue";
    }
    if (remainingDays <= 1) {
        return "critical";
    }
    if (remainingDays <= 2) {
        return "due-soon";
    }
    return "near";
};
