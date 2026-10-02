import "./ProjectWorkloadBadges.css";
import { useReducer } from "react";
import { useTranslation } from "react-i18next";
import Popover from "@/components/base/Popover";
import { ProjectColumn } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import { workloadColumns, workloadSearch, workloadTotal } from "./ProjectWorkload";

export default function ProjectWorkloadBadges({
    projectUID,
    compact = false,
    onNavigate,
}: {
    projectUID: string;
    compact?: boolean;
    onNavigate?: () => void;
}) {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const [, refresh] = useReducer((value) => value + 1, 0);
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === projectUID, [projectUID]);
    const total = workloadTotal(columns);
    const open = (columnUID?: string) => {
        navigate(`${ROUTES.BOARD.MAIN(projectUID)}${workloadSearch(columnUID)}`, { state: { commandPaletteFocus: true } });
        onNavigate?.();
    };
    const badges = workloadColumns(columns).map((column) => <ColumnBadge key={column.uid} column={column} onClick={() => open(column.uid)} />);
    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1" onClick={(event) => event.stopPropagation()}>
            {columns.map((column) => (
                <CountObserver key={column.uid} column={column} refresh={refresh} />
            ))}
            {total !== undefined && (
                <button
                    type="button"
                    className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-xs tabular-nums hover:bg-accent"
                    title={t("dashboard.Unfinished cards")}
                    aria-label={t("dashboard.Unfinished cards count", { count: total })}
                    onClick={() => open()}
                >
                    {total}
                </button>
            )}
            {compact
                ? total !== undefined && (
                      <>
                          <div className="project-workload-expanded">{badges}</div>
                          <Popover.Root>
                              <Popover.Trigger asChild>
                                  <button
                                      type="button"
                                      aria-label={t("dashboard.Unfinished by status")}
                                      className="project-workload-details rounded px-1 text-xs text-muted-foreground hover:bg-accent"
                                  >
                                      ▾
                                  </button>
                              </Popover.Trigger>
                              <Popover.Content className="flex max-w-64 flex-wrap gap-1">{badges}</Popover.Content>
                          </Popover.Root>
                      </>
                  )
                : badges}
        </div>
    );
}

function CountObserver({ column, refresh }: { column: ProjectColumn.TModel; refresh: () => void }) {
    column.useField("incomplete_count", refresh);
    column.useField("workflow_stage", refresh);
    column.useField("is_archive", refresh);
    column.useField("order", refresh);
    column.useField("name", refresh);
    return null;
}

function ColumnBadge({ column, onClick }: { column: ProjectColumn.TModel; onClick: () => void }) {
    const [t] = useTranslation();
    const name = column.useField("name");
    const count = column.useField("incomplete_count");
    if (count === undefined) return null;
    return (
        <button
            type="button"
            onClick={onClick}
            title={`${name}: ${count}`}
            aria-label={t("dashboard.Unfinished in status", { status: name, count })}
            className="flex min-w-0 items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs hover:bg-accent"
        >
            <span className="size-1.5 shrink-0 rounded-full" style={{ background: new Utils.Color.Generator(name).generateRandomColor() }} />
            <span className="max-w-24 truncate">{name}</span>
            <span className="tabular-nums">{count}</span>
        </button>
    );
}
