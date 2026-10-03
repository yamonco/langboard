import { formatNumber } from "@/core/utils/LocaleFormat";
import BoardCardInlineDeadline from "@/pages/BoardPage/components/card/BoardCardInlineDeadline";
import Button from "@/components/base/Button";
import { useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import DateTimePicker from "@/components/base/DateTimePicker";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Skeleton from "@/components/base/Skeleton";
import { ProjectRole } from "@/core/models/roles";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useBoard } from "@/core/providers/BoardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { useBoardCardSectionSaveActions } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { memo, type PointerEvent, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
    getDeadlinePressureLevel,
    getOverdueDays,
    getUpcomingDeadlineDays,
    isDeadlineWarningSuppressed,
} from "@/pages/BoardPage/components/board/BoardColumnCardStatus";

export function SkeletonBoardCardDeadline() {
    return <Skeleton h={{ initial: "8", lg: "10" }} className="w-1/3" />;
}

const serializeDeadline = (value: Date | undefined) => {
    if (!value) {
        return "";
    }

    const nextValue = new Date(value);
    nextValue.setSeconds(0, 0);
    return nextValue.toISOString();
};

const parseDeadline = (value: string) => {
    if (!value) {
        return undefined;
    }

    const nextValue = new Date(value);
    if (Number.isNaN(nextValue.getTime())) {
        return undefined;
    }

    nextValue.setSeconds(0, 0);
    return nextValue;
};

const BoardCardDeadlineDraft = memo(() => {
    const { card, hasRoleAction, isCardEditing } = useBoardCard();
    const [t, i18n] = useTranslation();
    const { registerSectionCancelHandler, registerSectionSaveHandler } = useBoardCardSectionSaveActions();
    const deadline = card.useField("deadline_at");
    const archivedAt = card.useField("archived_at");
    const checklistCompletedCount = card.useField("checklist_completed_count") ?? 0;
    const checklistTotalCount = card.useField("checklist_total_count") ?? 0;
    const { deadlineClock } = useBoard();
    const completed = card.useField("completed") ?? false;
    const workState = card.useField("work_state");
    const isFinished = isDeadlineWarningSuppressed({
        archivedAt,
        checklist: { completed: checklistCompletedCount, total: checklistTotalCount },
        completed,
        workState,
    });
    const isOverdue = getDeadlinePressureLevel({ deadlineAt: deadline, isCompleted: isFinished, now: deadlineClock }) === "overdue";
    const overdueDays = getOverdueDays({ deadlineAt: deadline, now: deadlineClock });
    const upcomingDays = getUpcomingDeadlineDays({ deadlineAt: deadline, now: deadlineClock, isCompleted: isFinished });
    const [isEditing, setIsEditing] = useState(false);
    const [draftDeadline, setDraftDeadline] = useState<Date | undefined>(deadline);
    const canStartEditing = hasRoleAction(ProjectRole.EAction.CardUpdate) && isCardEditing;
    const editable = canStartEditing && isEditing;

    const getNormalizedTime = useCallback((value: Date | undefined) => {
        if (!value) {
            return null;
        }

        const nextValue = new Date(value);
        nextValue.setSeconds(0, 0);
        return nextValue.getTime();
    }, []);

    const {
        isSynced,
        resetValue: resetCollaborativeDeadline,
        updateMeta: updateCollaborativeDeadlineMeta,
        updateValue: updateCollaborativeDeadline,
    } = useCollaborativeText({
        defaultValue: serializeDeadline(deadline),
        disabled: !editable,
        collaborationType: EEditorCollaborationType.Card,
        uid: card.uid,
        section: "deadline",
        field: "value",
        resetSyncedValueToDefault: true,
        onValueChange: (nextValue) => {
            const nextDeadline = parseDeadline(nextValue);
            setDraftDeadline(nextDeadline);
        },
    });
    const isWaitingForSync = editable && !isSynced;

    const handleChange = useCallback(
        (date: Date | undefined) => {
            const nextDeadline = date ? new Date(date) : undefined;
            nextDeadline?.setSeconds(0, 0);
            updateCollaborativeDeadline(serializeDeadline(nextDeadline));
        },
        [updateCollaborativeDeadline]
    );

    const handleStartEditing = useCallback(
        (e: PointerEvent<HTMLSpanElement>) => {
            if (!canStartEditing) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            requestAnimationFrame(() => {
                setDraftDeadline(deadline);
                setIsEditing(true);
            });
        },
        [canStartEditing, deadline]
    );

    const handleClearDeadline = useCallback(() => {
        updateCollaborativeDeadline("");
    }, [updateCollaborativeDeadline]);

    const saveDeadline = useCallback(() => {
        const nextDeadline = draftDeadline ? new Date(draftDeadline) : undefined;
        nextDeadline?.setSeconds(0, 0);

        if (getNormalizedTime(nextDeadline) === getNormalizedTime(deadline)) {
            resetCollaborativeDeadline(serializeDeadline(deadline));
            setIsEditing(false);
            return null;
        }

        const deadlineAt: Date | "" = nextDeadline || "";

        return { deadline_at: deadlineAt };
    }, [deadline, draftDeadline, getNormalizedTime, resetCollaborativeDeadline]);

    const cancelDeadline = useCallback(() => {
        resetCollaborativeDeadline(serializeDeadline(deadline));
        setDraftDeadline(deadline);
        setIsEditing(false);
    }, [deadline, resetCollaborativeDeadline]);

    useEffect(() => {
        if (!isCardEditing) {
            setIsEditing(false);
            setDraftDeadline(deadline);
        }
    }, [deadline, isCardEditing]);

    useEffect(() => {
        if (!editable || !isSynced) {
            return;
        }

        updateCollaborativeDeadlineMeta({ editing: true });

        return () => {
            updateCollaborativeDeadlineMeta(null);
        };
    }, [editable, isSynced, updateCollaborativeDeadlineMeta]);

    useEffect(() => registerSectionSaveHandler("deadline", saveDeadline), [registerSectionSaveHandler, saveDeadline]);
    useEffect(() => registerSectionCancelHandler("deadline", cancelDeadline), [cancelDeadline, registerSectionCancelHandler]);

    return (
        <>
            {!editable ? (
                <span
                    className={cn(
                        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors",
                        "h-8 px-4 py-2 lg:h-10",
                        deadline ? "bg-primary text-primary-foreground shadow" : "border border-input bg-background shadow-sm",
                        isOverdue && "bg-destructive/15 text-destructive ring-1 ring-destructive/50",
                        canStartEditing && "cursor-pointer hover:opacity-90"
                    )}
                    onPointerDown={handleStartEditing}
                >
                    {deadline ? Utils.String.formatDateLocale(deadline) : t("card.No deadline")}
                    {isOverdue && (
                        <span className="font-semibold">
                            {overdueDays > 0
                                ? t("card.Overdue by {{count}} day", { count: overdueDays, formatParams: { count: { lng: i18n.language } } })
                                : t("card.Overdue")}
                        </span>
                    )}
                    {upcomingDays !== null && (
                        <span className="font-semibold">
                            {upcomingDays === 0 ? t("card.D-Day") : t("card.D-{{count}}", { count: formatNumber(upcomingDays, i18n.language) })}
                        </span>
                    )}
                </span>
            ) : (
                <Flex items="center">
                    <DateTimePicker
                        value={draftDeadline}
                        disabled={isWaitingForSync}
                        min={new Date(new Date().setMinutes(new Date().getMinutes() + 30))}
                        onChange={handleChange}
                        timePicker={{
                            hour: true,
                            minute: true,
                            second: false,
                        }}
                        renderTrigger={() => (
                            <Button
                                type="button"
                                variant={draftDeadline ? "default" : "outline"}
                                className={cn("h-8 gap-2 px-3 lg:h-10", draftDeadline && "rounded-r-none")}
                                title={t("card.Set deadline")}
                                disabled={isWaitingForSync}
                            >
                                <IconComponent icon="calendar" size="4" />
                                {isWaitingForSync
                                    ? t("common.Syncing draft...")
                                    : draftDeadline
                                      ? Utils.String.formatDateLocale(draftDeadline)
                                      : t("card.Set deadline")}
                            </Button>
                        )}
                    />
                    {draftDeadline && (
                        <Button
                            type="button"
                            title={t("card.Remove deadline")}
                            aria-label={t("card.Remove deadline")}
                            variant="default"
                            className="h-8 gap-2 rounded-l-none border-l border-l-secondary/70 px-2 lg:h-10"
                            onClick={handleClearDeadline}
                            disabled={isWaitingForSync}
                        >
                            <IconComponent icon="trash-2" size="4" />
                        </Button>
                    )}
                </Flex>
            )}
        </>
    );
});

const BoardCardDeadline = memo(() => {
    const { isCardEditing } = useBoardCard();
    return isCardEditing ? <BoardCardDeadlineDraft /> : <BoardCardInlineDeadline />;
});

export default BoardCardDeadline;
