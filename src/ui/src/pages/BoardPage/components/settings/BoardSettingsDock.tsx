import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import useGetProjectDetails from "@/controllers/api/board/useGetProjectDetails";
import useReplaceProjectColumnDock from "@/controllers/api/board/useReplaceProjectColumnDock";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectColumn } from "@/core/models";
import { pinnedProjectDockColumns, reorderProjectDockDraft, ProjectDockSnapshot } from "@/core/models/projectDock";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";

export default function BoardSettingsDock() {
    const { project, canEditBasicInfo } = useBoardSettings();
    const revision = project.useField("dock_revision");
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === project.uid);
    const [draft, setDraft] = useState<ProjectDockSnapshot | null>(null);
    const [error, setError] = useState("");
    const pending = useRef(false);
    const { mutateAsync, isPending } = useReplaceProjectColumnDock({ interceptToast: true });
    const { refetch, isFetching } = useGetProjectDetails({ uid: project.uid }, { interceptToast: true });
    const [t] = useTranslation();
    const current = pinnedProjectDockColumns(columns).map((column) => column.uid);
    const selected = draft?.column_uids ?? current;
    const byUID = new Map(columns.map((column) => [column.uid, column]));
    const stale = !!draft && draft.revision !== revision;
    const unavailable = selected.some((uid) => !byUID.has(uid) || byUID.get(uid)?.is_archive);
    const busy = isPending || isFetching;
    const start = () => {
        setError("");
        const freshColumns = ProjectColumn.Model.getModels((column) => column.project_uid === project.uid);
        setDraft({ column_uids: pinnedProjectDockColumns(freshColumns).map((column) => column.uid), revision: project.dock_revision });
    };
    const reload = async () => {
        if (pending.current) return;
        pending.current = true;
        try {
            const result = await refetch();
            if (result.isError) throw result.error;
            start();
        } catch (caught) {
            const message = { message: "" };
            setupApiErrorHandler({}, message).handle(caught);
            setError(message.message);
        } finally {
            pending.current = false;
        }
    };
    const save = async () => {
        if (!draft || stale || unavailable || pending.current || !canEditBasicInfo) return;
        pending.current = true;
        setError("");
        try {
            await mutateAsync({ project_uid: project.uid, column_uids: draft.column_uids, expected_revision: draft.revision });
            setDraft(null);
        } catch (caught) {
            const message = { message: "" };
            setupApiErrorHandler({}, message).handle(caught);
            setError(message.message);
        } finally {
            pending.current = false;
        }
    };
    return (
        <div className="space-y-3 py-4">
            <p className="text-sm text-muted-foreground">{t("board.Dock shared description")}</p>
            {selected.length === 0 && <p className="text-sm text-muted-foreground">{t("board.No pinned columns")}</p>}
            <ol className="space-y-2">
                {selected.map((uid, index) => (
                    <li key={uid} className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/20 p-2">
                        <span className="min-w-0 flex-1 truncate text-sm">{byUID.get(uid)?.name ?? t("board.Column unavailable")}</span>
                        {draft && canEditBasicInfo && (
                            <>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    disabled={busy || index === 0}
                                    aria-label={t("board.Move shortcut earlier")}
                                    onClick={() => setDraft({ ...draft, column_uids: reorderProjectDockDraft(selected, index, -1) })}
                                >
                                    <IconComponent icon="arrow-up" size="4" />
                                </Button>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    disabled={busy || index === selected.length - 1}
                                    aria-label={t("board.Move shortcut later")}
                                    onClick={() => setDraft({ ...draft, column_uids: reorderProjectDockDraft(selected, index, 1) })}
                                >
                                    <IconComponent icon="arrow-down" size="4" />
                                </Button>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="icon"
                                    disabled={busy}
                                    aria-label={t("board.Unpin from dock")}
                                    onClick={() => setDraft({ ...draft, column_uids: selected.filter((item) => item !== uid) })}
                                >
                                    <IconComponent icon="x" size="4" />
                                </Button>
                            </>
                        )}
                    </li>
                ))}
            </ol>
            {draft && canEditBasicInfo && (
                <select
                    className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                    value=""
                    disabled={busy}
                    aria-label={t("board.Pin to dock")}
                    onChange={(event) => {
                        const uid = event.currentTarget.value;
                        if (uid && byUID.has(uid) && !byUID.get(uid)?.is_archive && !selected.includes(uid))
                            setDraft({ ...draft, column_uids: [...selected, uid] });
                    }}
                >
                    <option value="">{t("board.Pin to dock")}</option>
                    {columns
                        .filter((column) => !column.is_archive && !selected.includes(column.uid))
                        .map((column) => (
                            <option key={column.uid} value={column.uid}>
                                {column.name}
                            </option>
                        ))}
                </select>
            )}
            <div className="flex items-center gap-2 rounded-lg border border-dashed p-3 text-sm text-muted-foreground">
                <IconComponent icon="archive" size="4" />
                {t("board.Dock archive fixed")}
            </div>
            {(stale || unavailable) && (
                <p role="status" className="text-sm text-destructive">
                    {t("board.Dock reload required")}
                </p>
            )}
            {error && (
                <p role="alert" className="text-sm text-destructive">
                    {error}
                </p>
            )}
            {canEditBasicInfo && (
                <div className="flex flex-wrap gap-2">
                    {!draft ? (
                        <Button type="button" disabled={busy} onClick={start}>
                            {t("common.Edit")}
                        </Button>
                    ) : (
                        <>
                            <Button type="button" disabled={busy || stale || unavailable} onClick={() => void save()}>
                                {t("common.Save")}
                            </Button>
                            <Button type="button" variant="outline" disabled={busy} onClick={() => void reload()}>
                                {t("board.Reload dock")}
                            </Button>
                            <Button
                                type="button"
                                variant="ghost"
                                disabled={busy}
                                onClick={() => {
                                    setDraft(null);
                                    setError("");
                                }}
                            >
                                {t("common.Cancel")}
                            </Button>
                        </>
                    )}
                </div>
            )}
        </div>
    );
}
