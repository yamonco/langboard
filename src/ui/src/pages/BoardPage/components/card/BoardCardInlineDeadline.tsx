import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import DateTimePicker from "@/components/base/DateTimePicker";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useChangeCardDetails from "@/controllers/api/card/useChangeCardDetails";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useBoard } from "@/core/providers/BoardProvider";
import { ProjectRole } from "@/core/models/roles";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { formatNumber } from "@/core/utils/LocaleFormat";
import {
    getDeadlinePressureLevel,
    getOverdueDays,
    getUpcomingDeadlineDays,
    isDeadlineWarningSuppressed,
} from "@/pages/BoardPage/components/board/BoardColumnCardStatus";

export function InlineDeadlineField({
    deadline,
    canEdit,
    warning,
    overdue,
    save,
}: {
    deadline: Date | undefined;
    canEdit: boolean;
    warning?: string;
    overdue?: boolean;
    save: (value: Date | "") => Promise<unknown>;
}) {
    const [t] = useTranslation();
    const [isSaving, setIsSaving] = useState(false);
    const savingRef = useRef(false);
    const handleChange = async (value: Date | undefined) => {
        if (!canEdit || savingRef.current) return;
        const next = value ? new Date(value) : undefined;
        next?.setSeconds(0, 0);
        if (next?.getTime() === deadline?.getTime()) return;
        savingRef.current = true;
        setIsSaving(true);
        const promise = save(next ?? "");
        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            success: () => t("successes.Card changed successfully."),
            error: (error) => {
                const messageRef = { message: "" };
                setupApiErrorHandler({}, messageRef).handle(error);
                return messageRef.message;
            },
        });
        try {
            await promise;
        } catch {
            // Keep the confirmed value when the server rejects the change.
        } finally {
            savingRef.current = false;
            setIsSaving(false);
        }
    };
    const trigger = (
        <Button
            type="button"
            variant="outline"
            disabled={!canEdit || isSaving}
            className={cn(
                "h-auto min-h-10 min-w-0 max-w-full gap-2 whitespace-normal px-3 text-left",
                overdue && "border-destructive/50 bg-destructive/15 text-destructive"
            )}
            aria-label={t(deadline ? "card.Set deadline" : "card.Add deadline")}
            aria-busy={isSaving}
        >
            <IconComponent icon={deadline ? "calendar" : "plus"} size="4" />
            <span>{isSaving ? t("common.Changing...") : deadline ? Utils.String.formatDateLocale(deadline) : t("card.Add deadline")}</span>
            {warning && <span className="font-semibold">{warning}</span>}
        </Button>
    );
    return (
        <div className="flex min-w-0 flex-wrap items-center gap-1">
            {canEdit ? (
                <DateTimePicker
                    value={deadline}
                    disabled={isSaving}
                    min={new Date(new Date().setMinutes(new Date().getMinutes() + 30))}
                    timePicker={{ hour: true, minute: true, second: false }}
                    onChange={handleChange}
                    renderTrigger={() => trigger}
                />
            ) : deadline ? (
                trigger
            ) : (
                <span className="text-sm text-muted-foreground">{t("card.No deadline")}</span>
            )}
            {deadline && canEdit && (
                <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    disabled={isSaving}
                    className="size-10 shrink-0"
                    title={t("card.Remove deadline")}
                    aria-label={t("card.Remove deadline")}
                    onClick={() => handleChange(undefined)}
                >
                    <IconComponent icon="trash-2" size="4" />
                </Button>
            )}
        </div>
    );
}

export default function BoardCardInlineDeadline() {
    const { projectUID, card, hasRoleAction } = useBoardCard();
    const { deadlineClock } = useBoard();
    const [t, i18n] = useTranslation();
    const deadline = card.useField("deadline_at");
    const archivedAt = card.useField("archived_at");
    const completed = card.useField("completed") ?? false;
    const workState = card.useField("work_state");
    const checklistCompleted = card.useField("checklist_completed_count") ?? 0;
    const checklistTotal = card.useField("checklist_total_count") ?? 0;
    const { mutateAsync } = useChangeCardDetails({ interceptToast: true });
    const finished = isDeadlineWarningSuppressed({
        archivedAt,
        completed,
        workState,
        checklist: { completed: checklistCompleted, total: checklistTotal },
    });
    const overdue = getDeadlinePressureLevel({ deadlineAt: deadline, isCompleted: finished, now: deadlineClock }) === "overdue";
    const days = getOverdueDays({ deadlineAt: deadline, now: deadlineClock });
    const upcoming = getUpcomingDeadlineDays({ deadlineAt: deadline, now: deadlineClock, isCompleted: finished });
    const warning = overdue
        ? days > 0
            ? t("card.Overdue by {{count}} day", { count: days, formatParams: { count: { lng: i18n.language } } })
            : t("card.Overdue")
        : upcoming !== null
          ? upcoming === 0
              ? t("card.D-Day")
              : t("card.D-{{count}}", { count: formatNumber(upcoming, i18n.language) })
          : undefined;
    return (
        <InlineDeadlineField
            deadline={deadline}
            canEdit={hasRoleAction(ProjectRole.EAction.CardUpdate)}
            warning={warning}
            overdue={overdue}
            save={async (value) => {
                await mutateAsync({ project_uid: projectUID, card_uid: card.uid, deadline_at: value });
                card.deadline_at = value || undefined;
            }}
        />
    );
}
