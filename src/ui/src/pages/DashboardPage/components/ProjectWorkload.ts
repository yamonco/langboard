export interface WorkloadColumn {
    uid: string;
    name: string;
    order: number;
    is_archive: boolean;
    workflow_stage?: string | null;
    incomplete_count?: number;
    open_count?: number;
}

export function isUnfinishedColumn(column: Pick<WorkloadColumn, "name" | "is_archive" | "workflow_stage">): boolean {
    if (column.is_archive || ["closed", "reference"].includes(column.workflow_stage ?? "")) return false;
    // Match the existing legacy queue policy only while explicit workflow mapping is absent.
    return !!column.workflow_stage || !["done", "completed", "complete", "완료"].includes(column.name.trim().toLowerCase());
}

export function workloadColumns<TColumn extends WorkloadColumn>(columns: TColumn[]) {
    return columns.filter(isUnfinishedColumn).sort((a, b) => a.order - b.order);
}

export function workloadTotal(columns: WorkloadColumn[]): number | undefined {
    const visible = workloadColumns(columns);
    if (!columns.length || visible.some((column) => !Number.isSafeInteger(column.incomplete_count) || column.incomplete_count! < 0)) return undefined;
    return visible.reduce((total, column) => total + column.incomplete_count!, 0);
}

export function openWorkTotal(columns: WorkloadColumn[]): number | undefined {
    const visible = workloadColumns(columns);
    if (!columns.length || visible.some((column) => !Number.isSafeInteger(column.open_count) || column.open_count! < 0)) return undefined;
    // Authoritative open count excludes archived cards but retains completed checklists.
    return visible.reduce((total, column) => total + column.open_count!, 0);
}

export function workloadSearch(columnUID?: string): string {
    const filters = ["unfinished:yes"];
    if (columnUID) filters.push(`columns:${encodeURIComponent(encodeURIComponent(columnUID))}`);
    return `?${new URLSearchParams({ filters: filters.join(",") })}`;
}

export function matchesWorkload(
    card: {
        project_column_uid: string;
        source_type?: string | null;
        archived_at?: unknown;
        work_state?: { checklist_progress: { total: number; completed: number } };
    },
    column: Pick<WorkloadColumn, "name" | "is_archive" | "workflow_stage"> | undefined
): boolean {
    if (!column || !isUnfinishedColumn(column) || card.archived_at || card.source_type === "project_wiki") return false;
    const progress = card.work_state?.checklist_progress;
    return !progress || progress.total === 0 || progress.completed < progress.total;
}
