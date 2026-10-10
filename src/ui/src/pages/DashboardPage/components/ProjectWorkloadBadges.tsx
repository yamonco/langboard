import "./ProjectWorkloadBadges.css";
import { formatNumber } from "@/core/utils/LocaleFormat";
import { useReducer, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import Popover from "@/components/base/Popover";
import Tooltip from "@/components/base/Tooltip";
import { ProjectColumn } from "@/core/models";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ROUTES } from "@/core/routing/constants";
import { Utils } from "@langboard/core/utils";
import { openWorkTotal, workloadColumns, workloadSearch, workloadTotal } from "./ProjectWorkload";

export default function ProjectWorkloadBadges({
    projectUID,
    compact = false,
    onNavigate,
}: {
    projectUID: string;
    compact?: boolean;
    onNavigate?: () => void;
}) {
    const [t, i18n] = useTranslation();
    const navigate = usePageNavigateRef();
    const [, refresh] = useReducer((value) => value + 1, 0);
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === projectUID, [projectUID]);
    const total = workloadTotal(columns);
    const openTotal = openWorkTotal(columns);
    const open = (columnUID?: string) => {
        navigate(`${ROUTES.BOARD.MAIN(projectUID)}${workloadSearch(columnUID)}`, { state: { commandPaletteFocus: true } });
        onNavigate?.();
    };
    const visible = workloadColumns(columns);
    const maximum = Math.max(0, ...visible.map((column) => column.incomplete_count ?? 0));
    const details = <WorkloadPie columns={visible} total={total ?? 0} />;
    const graphs = (inPopover = false) =>
        visible.map((column) => (
            <ColumnGraph
                key={column.uid}
                column={column}
                maximum={maximum}
                details={details}
                inPopover={inPopover}
                onClick={() => open(column.uid)}
            />
        ));
    return (
        <div
            className={`flex min-w-0 flex-wrap items-center gap-1 ${compact ? "max-w-[60%] shrink-0" : ""}`}
            onClick={(event) => event.stopPropagation()}
        >
            {columns.map((column) => (
                <CountObserver key={column.uid} column={column} refresh={refresh} />
            ))}
            {openTotal !== undefined && (
                <span
                    className="shrink-0 rounded-md bg-muted/60 px-1.5 py-0.5 text-xs font-medium tabular-nums text-muted-foreground"
                    title={t("dashboard.Open cards")}
                    aria-label={t("dashboard.Open cards count", { count: openTotal })}
                >
                    {formatNumber(openTotal, i18n.language)}
                </span>
            )}
            {compact
                ? total !== undefined && (
                      <>
                          <div className="project-workload-expanded">{graphs()}</div>
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
                              <Popover.Content className="max-w-64">
                                  <div className="flex gap-1">{graphs(true)}</div>
                                  {details}
                              </Popover.Content>
                          </Popover.Root>
                      </>
                  )
                : graphs()}
        </div>
    );
}

function CountObserver({ column, refresh }: { column: ProjectColumn.TModel; refresh: () => void }) {
    column.useField("incomplete_count", refresh);
    column.useField("count", refresh);
    column.useField("open_count", refresh);
    column.useField("workflow_stage", refresh);
    column.useField("workflow_counts_as_completed", refresh);
    column.useField("is_archive", refresh);
    column.useField("order", refresh);
    column.useField("name", refresh);
    return null;
}

function ColumnGraph({
    column,
    maximum,
    details,
    inPopover,
    onClick,
}: {
    column: ProjectColumn.TModel;
    maximum: number;
    details: ReactNode;
    inPopover: boolean;
    onClick: () => void;
}) {
    const [t] = useTranslation();
    const name = column.useField("name");
    const count = column.useField("incomplete_count");
    if (count === undefined) return null;
    const ratio = maximum > 0 ? Math.min(1, Math.max(0, count / maximum)) : 0;
    return (
        <Tooltip.Root open={inPopover ? false : undefined}>
            <Tooltip.Trigger asChild>
                <button
                    type="button"
                    onClick={onClick}
                    aria-label={t("dashboard.Unfinished in status", { status: name, count })}
                    className="flex min-w-0 items-center rounded px-0.5 py-0.5 hover:bg-accent focus-visible:outline focus-visible:outline-2"
                >
                    <span
                        aria-hidden="true"
                        data-workload-column={column.uid}
                        data-workload-value={count}
                        data-workload-max={maximum}
                        className="flex h-6 w-2 shrink-0 items-end overflow-hidden rounded-sm bg-muted"
                    >
                        <span
                            className="w-full rounded-sm"
                            style={{ height: `${ratio * 100}%`, background: new Utils.Color.Generator(name).generateRandomColor() }}
                        />
                    </span>
                </button>
            </Tooltip.Trigger>
            <Tooltip.Portal>
                <Tooltip.Content>{details}</Tooltip.Content>
            </Tooltip.Portal>
        </Tooltip.Root>
    );
}

function WorkloadPie({ columns, total }: { columns: ProjectColumn.TModel[]; total: number }) {
    const [t, i18n] = useTranslation();
    let offset = 0;
    const segments = columns.map((column) => {
        const start = offset;
        offset += total > 0 ? ((column.incomplete_count ?? 0) / total) * 100 : 0;
        return `${new Utils.Color.Generator(column.name).generateRandomColor()} ${start}% ${offset}%`;
    });
    return (
        <div className="flex max-w-64 items-center gap-3 py-1">
            <span
                role="img"
                aria-label={t("dashboard.Unfinished cards count", { count: total })}
                data-workload-pie="true"
                className="size-16 shrink-0 rounded-full bg-muted"
                style={{ background: total > 0 ? `conic-gradient(${segments.join(",")})` : undefined }}
            />
            <div className="flex min-w-0 flex-col gap-1 text-xs">
                {columns.map((column) => (
                    <span key={column.uid} className="flex items-center gap-1.5">
                        <span
                            className="size-1.5 shrink-0 rounded-full"
                            style={{ background: new Utils.Color.Generator(column.name).generateRandomColor() }}
                        />
                        <span className="truncate">{column.name}</span>
                        <span className="ml-auto tabular-nums">{formatNumber(column.incomplete_count ?? 0, i18n.language)}</span>
                    </span>
                ))}
            </div>
        </div>
    );
}
