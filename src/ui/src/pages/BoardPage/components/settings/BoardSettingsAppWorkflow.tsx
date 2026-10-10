import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { ProjectColumn } from "@/core/models";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import type { IWorkflowStage } from "@/controllers/api/settings/workflowStages/useWorkflowStages";
import { metadataDisplay } from "@/core/utils/MetadataDisplay";

interface Snapshot {
    workflow_stages: Record<string, IWorkflowStage>;
    column_names: Record<string, string>;
    available_columns: { uid: string; name: string; workflow_stage: string | null }[];
    binding: { uid: string; revision: string; workflow_mapping: Record<string, string> } | null;
    choices: { stage: string; required: boolean; status: string; column_uid: string | null; candidates: string[] }[];
}
export default function BoardSettingsAppWorkflow({ appKey, onDirtyChange }: { appKey: string; onDirtyChange?: (dirty: boolean) => void }) {
    const [t, i18n] = useTranslation();
    const { project, canEditBasicInfo } = useBoardSettings();
    const columns = ProjectColumn.Model.useModels((column) => column.project_uid === project.uid);
    const app = appKey;
    const [draft, setDraft] = useState<Record<string, string>>({});
    const [pending, setPending] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [draftRevision, setDraftRevision] = useState<string | null>(null);
    const [repairColumns, setRepairColumns] = useState<Record<string, string>>({});
    const [replacement, setReplacement] = useState<{ stage: string; columnUID: string } | null>(null);
    const [newNames, setNewNames] = useState<Record<string, string>>({});
    const [error, setError] = useState(false);
    const { query } = useQueryMutation();
    useEffect(() => {
        onDirtyChange?.(dirty || pending);
    }, [dirty, pending, onDirtyChange]);
    const url = `/board/${project.uid}/settings/apps/${encodeURIComponent(app)}/workflow`;
    const { data, isLoading, isError, refetch } = query(["app-workflow", project.uid, app], async () => (await api.get(url)).data as Snapshot, {
        retry: 0,
    });
    const stageName = (key: string) => {
        const stage = data?.workflow_stages?.[key];
        return stage ? metadataDisplay(stage, stage.translations, i18n.resolvedLanguage ?? i18n.language).name : key;
    };
    useEffect(() => {
        if (!dirty) {
            setDraft(data?.binding?.workflow_mapping ?? {});
            setError(false);
            setDraftRevision(null);
        }
    }, [data, app, dirty]);
    useEffect(() => {
        setRepairColumns({});
        setNewNames({});
        setReplacement(null);
    }, [app]);
    const save = async () => {
        if (pending || !canEditBasicInfo || !data) return;
        setPending(true);
        setError(false);
        try {
            if (!data.binding) await api.post(url);
            else
                await api.put(url, {
                    binding_uid: data.binding.uid,
                    workflow_mapping: Object.fromEntries(Object.entries(draft).filter(([, uid]) => uid)),
                    expected_revision: draftRevision ?? data.binding.revision,
                    enable_transitions: false,
                });
            setDirty(false);
            await refetch();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    const repair = async (stage: string, create: boolean, confirmed = false) => {
        if (pending || dirty || !canEditBasicInfo || !data?.binding) return;
        const columnUID = repairColumns[stage];
        const name = newNames[stage]?.trim();
        if (create ? !name : !columnUID) return;
        const currentColumn = data.available_columns.find((column) => column.uid === columnUID);
        if (!create && currentColumn?.workflow_stage && currentColumn.workflow_stage !== stage && !confirmed) {
            setReplacement({ stage, columnUID });
            return;
        }
        setReplacement(null);
        setPending(true);
        setError(false);
        try {
            if (create) await api.post(`/board/${project.uid}/column`, { name, workflow_stage: stage });
            else
                await api.put(`/board/${project.uid}/column/${columnUID}/workflow-stage`, {
                    workflow_stage: stage,
                    expected_workflow_stage: currentColumn?.workflow_stage ?? null,
                });
            setRepairColumns({});
            setNewNames({});
            await refetch();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    return (
        <div className="flex w-full flex-col gap-4 py-4">
            <p className="text-sm text-muted-foreground">{t("project.settings.App workflow draft help")}</p>
            {isLoading ? (
                <p role="status">{t("common.Loading...")}</p>
            ) : isError ? (
                <p role="alert">{t("project.settings.App workflow unavailable")}</p>
            ) : (
                data && (
                    <div className="grid gap-3 sm:grid-cols-2">
                        {data.choices.map((choice) => (
                            <div key={choice.stage} className="flex min-w-0 flex-col gap-2 rounded-lg border p-3 text-sm">
                                <span>
                                    {stageName(choice.stage)} · {t(`project.settings.${choice.required ? "Required" : "Optional"}`)}
                                </span>
                                <select
                                    className="min-w-0 rounded-md border border-input bg-background p-2"
                                    value={Object.hasOwn(draft, choice.stage) ? draft[choice.stage] : (choice.column_uid ?? "")}
                                    disabled={!canEditBasicInfo || pending || !data.binding}
                                    onChange={(event) => {
                                        if (!dirty) setDraftRevision(data.binding?.revision ?? null);
                                        setDirty(true);
                                        setDraft((current) => {
                                            const next = { ...current };
                                            if (event.target.value) next[choice.stage] = event.target.value;
                                            else next[choice.stage] = "";
                                            return next;
                                        });
                                    }}
                                >
                                    <option value="">{t("project.settings.Select column")}</option>
                                    {draft[choice.stage] && !choice.candidates.includes(draft[choice.stage]) && (
                                        <option value={draft[choice.stage]}>{t("project.settings.Previous column unavailable")}</option>
                                    )}
                                    {choice.candidates.map((uid) => (
                                        <option key={uid} value={uid}>
                                            {columns.find((column) => column.uid === uid)?.name ??
                                                data.column_names[uid] ??
                                                t("project.settings.Column")}
                                        </option>
                                    ))}
                                </select>
                                <span className="text-xs text-muted-foreground">{t(`project.settings.Mapping ${choice.status}`)}</span>
                                {choice.status === "missing" && (
                                    <div className="flex flex-col gap-2 border-t pt-2">
                                        <select
                                            aria-label={t("project.settings.Existing column for stage")}
                                            className="min-w-0 rounded-md border border-input bg-background p-2"
                                            value={repairColumns[choice.stage] ?? ""}
                                            disabled={!canEditBasicInfo || pending || dirty || !data.binding}
                                            onChange={(event) => {
                                                setReplacement(null);
                                                setRepairColumns((current) => ({ ...current, [choice.stage]: event.target.value }));
                                            }}
                                        >
                                            <option value="">{t("project.settings.Select column")}</option>
                                            {(data.available_columns ?? []).map((column) => (
                                                <option key={column.uid} value={column.uid}>
                                                    {column.name}
                                                    {column.workflow_stage ? ` · ${stageName(column.workflow_stage)}` : ""}
                                                </option>
                                            ))}
                                        </select>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            disabled={!canEditBasicInfo || pending || dirty || !data.binding || !repairColumns[choice.stage]}
                                            onClick={() => void repair(choice.stage, false)}
                                        >
                                            {t("project.settings.Assign stage to column")}
                                        </Button>
                                        {replacement?.stage === choice.stage && replacement.columnUID === repairColumns[choice.stage] && (
                                            <div className="flex flex-col gap-2 rounded-md bg-muted p-2">
                                                <p role="status" className="text-xs">
                                                    {t("project.settings.Replace column stage warning")}
                                                </p>
                                                <Button
                                                    type="button"
                                                    size="sm"
                                                    variant="outline"
                                                    disabled={!canEditBasicInfo || pending || dirty || !data.binding}
                                                    onClick={() => void repair(choice.stage, false, true)}
                                                >
                                                    {t("project.settings.Confirm stage replacement")}
                                                </Button>
                                                <Button type="button" size="sm" variant="ghost" onClick={() => setReplacement(null)}>
                                                    {t("common.Cancel")}
                                                </Button>
                                            </div>
                                        )}
                                        <input
                                            aria-label={t("project.settings.New workflow column name")}
                                            className="min-w-0 rounded-md border border-input bg-background p-2"
                                            maxLength={100}
                                            value={newNames[choice.stage] ?? ""}
                                            disabled={!canEditBasicInfo || pending || dirty || !data.binding}
                                            onChange={(event) => setNewNames((current) => ({ ...current, [choice.stage]: event.target.value }))}
                                        />
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant="outline"
                                            disabled={!canEditBasicInfo || pending || dirty || !data.binding || !newNames[choice.stage]?.trim()}
                                            onClick={() => void repair(choice.stage, true)}
                                        >
                                            {t("project.settings.Create column with stage")}
                                        </Button>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )
            )}
            {error && (
                <p role="alert" className="text-sm text-destructive">
                    {t("project.settings.App workflow save failed")}
                </p>
            )}
            <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={!canEditBasicInfo || pending || !data} onClick={() => void save()}>
                    {t(`project.settings.${data?.binding ? "Save workflow mapping" : "Prepare workflow settings"}`)}
                </Button>
                {dirty && (
                    <Button size="sm" variant="outline" disabled={pending} onClick={() => setDirty(false)}>
                        {t("project.settings.Discard workflow changes")}
                    </Button>
                )}
                <Button size="sm" variant="outline" disabled={pending || dirty} onClick={() => void refetch()}>
                    {t("common.Retry")}
                </Button>
            </div>
        </div>
    );
}
