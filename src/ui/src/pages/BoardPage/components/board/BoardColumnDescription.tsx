import Button from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Textarea from "@/components/base/Textarea";
import Toast from "@/components/base/Toast";
import { DISABLE_DRAGGING_ATTR } from "@/constants";
import useChangeProjectColumnDescription from "@/controllers/api/board/useChangeProjectColumnDescription";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { ProjectColumn } from "@/core/models";
import { ProjectRole } from "@/core/models/roles";
import { useBoard } from "@/core/providers/BoardProvider";
import { useState } from "react";
import { useTranslation } from "react-i18next";

/** Readable workflow guidance, editable only by board editors. */
function BoardColumnDescription({ column }: { column: ProjectColumn.TModel }) {
    const [t] = useTranslation();
    const { hasRoleAction } = useBoard();
    const description = column.useField("description") ?? "";
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState(description);
    const { mutateAsync: saveDescription, isPending } = useChangeProjectColumnDescription({ interceptToast: true });
    const canEdit = hasRoleAction(ProjectRole.EAction.Update) && !column.is_archive;

    const save = async () => {
        try {
            const saved = await saveDescription({ project_uid: column.project_uid, project_column_uid: column.uid, description: draft });
            column.description = saved.description;
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
                if (value) setDraft(description);
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
                            disabled={isPending}
                            placeholder={t("project.When should a card enter this column?")}
                        />
                        <div className="flex justify-end gap-2">
                            <Button variant="ghost" disabled={isPending} onClick={() => setOpen(false)}>
                                {t("common.Cancel")}
                            </Button>
                            <Button disabled={isPending || draft === description} onClick={save}>
                                {t("common.Save")}
                            </Button>
                        </div>
                    </>
                ) : (
                    <p className="whitespace-pre-wrap break-words text-sm">{description || t("project.No column description")}</p>
                )}
            </Popover.Content>
        </Popover.Root>
    );
}

export default BoardColumnDescription;
