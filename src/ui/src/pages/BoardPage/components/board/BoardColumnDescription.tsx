import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Textarea from "@/components/base/Textarea";
import Toast from "@/components/base/Toast";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import useChangeProjectColumnDescription from "@/controllers/api/board/useChangeProjectColumnDescription";
import useChangeProjectColumnWorkflowStage from "@/controllers/api/board/useChangeProjectColumnWorkflowStage";
import useProjectWorkflowStages from "@/controllers/api/board/useProjectWorkflowStages";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectColumn } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Readable workflow guidance, editable only by board editors. */
function BoardColumnDescription({ column }: { column: ProjectColumn.TModel }) {
    const [t, i18n] = useTranslation();
    const { hasRoleAction } = useBoard();
    const description = column.useField("description") ?? "";
    const workflowStage = column.useField("workflow_stage") ?? null;
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState(description);
    const [stageDraft, setStageDraft] = useState(workflowStage);
    const { mutateAsync: saveDescription, isPending } = useChangeProjectColumnDescription({ interceptToast: true });
    const { mutateAsync: saveStage, isPending: isStagePending } = useChangeProjectColumnWorkflowStage({ interceptToast: true });
    const canEdit = hasRoleAction(ProjectRole.EAction.Update) && !column.is_archive;

    const stages = useProjectWorkflowStages(column.project_uid, open);
    const selectedStage = stages.data?.find((stage) => stage.key === stageDraft);
    const localized = (stage: NonNullable<typeof selectedStage>) =>
        stage.translations[i18n.resolvedLanguage ?? "en"] ??
        stage.translations[(i18n.resolvedLanguage ?? "en").split("-")[0]] ??
        stage.translations.en;

    const save = async () => {
        try {
            if (draft !== description) {
                const saved = await saveDescription({ project_uid: column.project_uid, project_column_uid: column.uid, description: draft });
                column.description = saved.description;
            }
            if (stageDraft !== workflowStage) {
                const saved = await saveStage({ project_uid: column.project_uid, project_column_uid: column.uid, workflow_stage: stageDraft });
                column.workflow_stage = saved.workflow_stage ?? null;
            }
            setOpen(false);
        } catch (error) {
            const messageRef = { message: "" };
            const { handle } = setupApiErrorHandler({}, messageRef);
            handle(error);
            Toast.Add.error(messageRef.message);
        }
    };

    if (column.is_archive) return null;
    return (
        <Popover.Root
            open={open}
            onOpenChange={(value) => {
                if (value) {
                    setDraft(description);
                    setStageDraft(workflowStage);
                }
                setOpen(value);
            }}
        >
            <Popover.Trigger asChild>
                <Button
                    variant="ghost"
                    size="icon"
                    className="size-7 shrink-0"
                    aria-label={t("project.Column description")}
                    {...{ [DISABLE_DRAGGING_ATTR]: "" }}
                >
                    <IconComponent icon="info" className="size-4" />
                </Button>
            </Popover.Trigger>
            <Popover.Content align="start" className="w-80 max-w-[calc(100vw-2rem)] space-y-3" {...{ [DISABLE_DRAGGING_ATTR]: "" }}>
                <p className="font-medium">{t("project.Column description")}</p>
                {canEdit ? (
                    <>
                        <Textarea
                            aria-label={t("project.Column description")}
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            maxLength={4096}
                            rows={5}
                            disabled={isPending || isStagePending}
                            placeholder={t("project.When should a card enter this column?")}
                        />
                        <label className="block space-y-1 text-sm">
                            <span>Workflow stage</span>
                            <select
                                aria-label={t("common.Workflow stage")}
                                className="w-full rounded border border-input bg-background px-2 py-1.5"
                                value={stageDraft ?? ""}
                                onChange={(event) => setStageDraft((event.target.value || null) as typeof stageDraft)}
                                disabled={isPending || isStagePending || stages.isLoading || !!stages.error}
                            >
                                <option value="">Unclassified</option>
                                {workflowStage && !stages.data?.some((stage) => stage.key === workflowStage) && (
                                    <option value={workflowStage} disabled>
                                        {workflowStage}
                                    </option>
                                )}
                                {stages.data?.map((stage) => (
                                    <option key={stage.key} value={stage.key} disabled={!stage.is_active && stage.key !== workflowStage}>
                                        {localized(stage)?.name || stage.name}
                                        {!stage.is_active ? " (Inactive)" : ""}
                                    </option>
                                ))}
                            </select>
                        </label>
                        {stages.error && (
                            <p role="alert" className="text-sm text-destructive">
                                Workflow stages could not be loaded.
                            </p>
                        )}
                        {selectedStage && (
                            <div className="space-y-1 rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
                                <p className="whitespace-pre-wrap">{localized(selectedStage)?.description || selectedStage.description}</p>
                                <p>
                                    {selectedStage.counts_as_completed ? "Completed · " : ""}Queue {selectedStage.active_queue_policy} · Overdue{" "}
                                    {selectedStage.overdue_policy}
                                </p>
                                <p>Entry effects: {selectedStage.entry_effects.length}</p>
                                {selectedStage.entry_effects.map((effect) => (
                                    <p key={effect}>{effect === "complete_checkitems" ? "Complete unchecked items" : "Stop running timers"}</p>
                                ))}
                            </div>
                        )}
                        <div className="flex justify-end gap-2">
                            <Button variant="ghost" disabled={isPending || isStagePending} onClick={() => setOpen(false)}>
                                {t("common.Cancel")}
                            </Button>
                            <Button disabled={isPending || isStagePending || (draft === description && stageDraft === workflowStage)} onClick={save}>
                                {t("common.Save")}
                            </Button>
                        </div>
                    </>
                ) : (
                    <>
                        <p className="whitespace-pre-wrap break-words text-sm">{description || t("project.No column description")}</p>
                        <p className="text-xs text-muted-foreground">Workflow stage: {workflowStage ?? "Unclassified"}</p>
                    </>
                )}
            </Popover.Content>
        </Popover.Root>
    );
}

export default BoardColumnDescription;
