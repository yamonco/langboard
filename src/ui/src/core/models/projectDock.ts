export interface ProjectDockSnapshot {
    column_uids: string[];
    revision: number;
}

export function retainProjectDockSnapshot(currentRevision: number, snapshot: ProjectDockSnapshot): ProjectDockSnapshot | null {
    if (!Number.isSafeInteger(snapshot.revision) || snapshot.revision < currentRevision || snapshot.revision < 0) return null;
    if (!Array.isArray(snapshot.column_uids) || snapshot.column_uids.some((uid) => typeof uid !== "string" || !uid)) return null;
    if (new Set(snapshot.column_uids).size !== snapshot.column_uids.length) return null;
    return { revision: snapshot.revision, column_uids: [...snapshot.column_uids] };
}

export function monotonicProjectDockRevision(current: number, incoming: unknown): number {
    return typeof incoming === "number" && Number.isSafeInteger(incoming) && incoming >= current ? incoming : current;
}

export function preserveProjectDockMetadata<T extends { dock_order?: number | null }>(incoming: T, current: number | null): T {
    return { ...incoming, dock_order: current };
}

export function reorderProjectDockDraft(columns: readonly string[], index: number, direction: -1 | 1): string[] {
    const next = [...columns];
    const destination = index + direction;
    if (!Number.isSafeInteger(index) || index < 0 || index >= next.length || destination < 0 || destination >= next.length) return next;
    [next[index], next[destination]] = [next[destination], next[index]];
    return next;
}

interface DockColumn {
    uid: string;
    is_archive: boolean;
    dock_order: number | null;
}

export function pinnedProjectDockColumns<T extends DockColumn>(columns: readonly T[]): T[] {
    return columns
        .filter((column) => !column.is_archive && column.dock_order !== null && Number.isSafeInteger(column.dock_order) && column.dock_order >= 0)
        .sort((a, b) => a.dock_order! - b.dock_order! || a.uid.localeCompare(b.uid));
}

export function applyProjectDockProjection(project: { dock_revision: number }, columns: DockColumn[], snapshot: ProjectDockSnapshot): boolean {
    if (!Number.isSafeInteger(snapshot.revision) || snapshot.revision < project.dock_revision || snapshot.revision < 0) return false;
    if (!Array.isArray(snapshot.column_uids) || snapshot.column_uids.some((uid) => typeof uid !== "string" || !uid)) return false;
    const positions = new Map(snapshot.column_uids.map((uid, index) => [uid, index]));
    const eligible = new Set(columns.filter((column) => !column.is_archive).map((column) => column.uid));
    if (positions.size !== snapshot.column_uids.length || snapshot.column_uids.some((uid) => !eligible.has(uid))) return false;
    for (const column of columns) {
        const order = positions.get(column.uid) ?? null;
        if (column.dock_order !== order) column.dock_order = order;
    }
    project.dock_revision = snapshot.revision;
    return true;
}
