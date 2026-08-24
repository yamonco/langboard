import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import { useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import type { ICollaborativeTextMeta } from "@/components/Collaborative/useCollaborativeText";
import BotScheduleListItemForm, { IBotScheduleControlMeta, IBotScheduleTriggersMap } from "@/components/bots/BotScheduleList/ItemForm";
import { IBotScheduleFormMap, useBotScheduleList } from "@/components/bots/BotScheduleList/Provider";
import useRescheduleBotCron from "@/controllers/api/shared/botSchedules/useRescheduleBotCron";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { BaseBotScheduleModel } from "@/core/models";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBotScheduleListItemEditProps {
    schedule: BaseBotScheduleModel.TModel;
    variant?: React.ComponentProps<typeof Button>["variant"];
    className?: string;
}

interface IBotScheduleDraftValue {
    runningType?: BaseBotScheduleModel.ERunningType;
    startAt?: string | null;
    endAt?: string | null;
    interval?: string;
}

const isBotScheduleControlMeta = (value: unknown): value is IBotScheduleControlMeta => {
    if (!value || typeof value !== "object") {
        return false;
    }

    const meta = value as Partial<IBotScheduleControlMeta>;
    return typeof meta.field === "string" && typeof meta.label === "string" && typeof meta.updatedAt === "number";
};

const isBotScheduleRunningType = (value: unknown): value is BaseBotScheduleModel.ERunningType => {
    return Object.values(BaseBotScheduleModel.ERunningType).includes(value as BaseBotScheduleModel.ERunningType);
};

const parseBotScheduleDate = (value?: string | null) => {
    if (!value) {
        return undefined;
    }

    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? undefined : date;
};

const serializeBotScheduleDraft = (valuesMap: IBotScheduleFormMap) => {
    const value: IBotScheduleDraftValue = {
        runningType: valuesMap.runningType,
        interval: valuesMap.interval,
        startAt: valuesMap.startAt?.toISOString() ?? null,
        endAt: valuesMap.endAt?.toISOString() ?? null,
    };

    return JSON.stringify(value);
};

const parseBotScheduleDraft = (value: string, fallback: IBotScheduleFormMap): IBotScheduleFormMap => {
    try {
        const parsed = JSON.parse(value) as IBotScheduleDraftValue;
        return {
            runningType: isBotScheduleRunningType(parsed.runningType) ? parsed.runningType : fallback.runningType,
            interval: typeof parsed.interval === "string" ? parsed.interval : fallback.interval,
            startAt: parseBotScheduleDate(parsed.startAt),
            endAt: parseBotScheduleDate(parsed.endAt),
        };
    } catch {
        return fallback;
    }
};

function BotScheduleListItemEdit({
    schedule,
    variant = "outline",
    className = "border-0 [&:first-child]:rounded-b-none [&:not(:first-child)]:rounded-t-none [&:not(:first-child)]:border-t",
}: IBotScheduleListItemEditProps): React.JSX.Element {
    const { bot, params, target } = useBotScheduleList();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const projectUID = "project_uid" in target ? target.project_uid : target.uid;
    const { mutateAsync: rescheduleBotCronMutateAsync } = useRescheduleBotCron(
        { ...params, bot_uid: bot.uid, project_uid: projectUID, schedule_uid: schedule.uid },
        { interceptToast: true }
    );
    const runningType = schedule.useField("running_type");
    const rawIntervalStr = schedule.useField("interval_str");
    const intervalStr = useMemo(() => Utils.String.Crontab.restoreTimezone(rawIntervalStr), [rawIntervalStr]);
    const startAt = schedule.useField("start_at");
    const endAt = schedule.useField("end_at");
    const originalValuesMap = useMemo<IBotScheduleFormMap>(
        () => ({
            runningType: runningType,
            interval: intervalStr,
            startAt: startAt,
            endAt: endAt,
        }),
        [runningType, intervalStr, startAt, endAt]
    );
    const valuesMapRef = useRef<IBotScheduleFormMap>(originalValuesMap);
    const triggersMapRef = useRef<IBotScheduleTriggersMap>({});
    const [isOpened, setIsOpened] = useState(false);
    const [syncedValuesMap, setSyncedValuesMap] = useState<IBotScheduleFormMap>(originalValuesMap);
    const isApplyingRemoteDraftRef = useRef(false);
    const remoteDraftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const editStartedAtRef = useRef(0);
    const scheduleDraftSync = useCollaborativeText({
        collaborationType: EEditorCollaborationType.BotSchedule,
        uid: projectUID,
        section: `${params.target_table}-${target.uid}-${schedule.uid}`,
        field: "schedule",
        defaultValue: serializeBotScheduleDraft(originalValuesMap),
        disabled: !isOpened,
        onValueChange: (nextValue) => {
            isApplyingRemoteDraftRef.current = true;
            if (remoteDraftTimerRef.current) {
                clearTimeout(remoteDraftTimerRef.current);
            }

            const nextValuesMap = parseBotScheduleDraft(nextValue, originalValuesMap);
            valuesMapRef.current = nextValuesMap;
            setSyncedValuesMap(nextValuesMap);
            remoteDraftTimerRef.current = setTimeout(() => {
                isApplyingRemoteDraftRef.current = false;
                remoteDraftTimerRef.current = null;
            }, 0);
        },
    });
    const remoteControlMeta = useMemo(() => {
        return scheduleDraftSync.remoteMeta.reduce<Record<string, ICollaborativeTextMeta<IBotScheduleControlMeta>>>((acc, meta) => {
            if (!isBotScheduleControlMeta(meta.value)) {
                return acc;
            }

            const parsedMeta = meta as ICollaborativeTextMeta<IBotScheduleControlMeta>;
            if (parsedMeta.value.updatedAt < editStartedAtRef.current) {
                return acc;
            }

            const previousMeta = acc[parsedMeta.value.field];
            if (!previousMeta || previousMeta.value.updatedAt < parsedMeta.value.updatedAt) {
                acc[parsedMeta.value.field] = parsedMeta;
            }

            return acc;
        }, {});
    }, [scheduleDraftSync.remoteMeta]);

    useEffect(() => {
        return () => {
            if (remoteDraftTimerRef.current) {
                clearTimeout(remoteDraftTimerRef.current);
            }
        };
    }, []);

    useEffect(() => {
        if (isOpened) {
            return;
        }

        valuesMapRef.current = originalValuesMap;
        setSyncedValuesMap(originalValuesMap);
    }, [isOpened, originalValuesMap]);

    const changeOpenedState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        if (opened) {
            editStartedAtRef.current = Date.now();
            scheduleDraftSync.updateMeta(null);
            const nextValuesMap = parseBotScheduleDraft(scheduleDraftSync.value, originalValuesMap);
            valuesMapRef.current = nextValuesMap;
            setSyncedValuesMap(nextValuesMap);
        } else {
            scheduleDraftSync.updateMeta(null);
            editStartedAtRef.current = 0;
        }
        setIsOpened(opened);
    };

    const syncValuesMap = (nextValuesMap: IBotScheduleFormMap, field: string, label: string) => {
        setSyncedValuesMap(nextValuesMap);
        if (isApplyingRemoteDraftRef.current) {
            return;
        }

        scheduleDraftSync.updateValue(serializeBotScheduleDraft(nextValuesMap));
        scheduleDraftSync.updateMeta({
            field,
            label,
            updatedAt: Date.now(),
        } satisfies IBotScheduleControlMeta);
    };

    const createSchedule = () => {
        if (isValidating) {
            return;
        }

        valuesMapRef.current.runningType = valuesMapRef.current.runningType ?? BaseBotScheduleModel.ERunningType.Infinite;

        if (BaseBotScheduleModel.RUNNING_TYPES_WITH_START_AT.includes(valuesMapRef.current.runningType)) {
            if (!valuesMapRef.current.startAt) {
                Toast.Add.error(t("bot.schedules.errors.Cron start time is required."));
                triggersMapRef.current.startAt?.focus();
                return;
            }
        }

        if (BaseBotScheduleModel.RUNNING_TYPES_WITH_END_AT.includes(valuesMapRef.current.runningType)) {
            if (!valuesMapRef.current.endAt) {
                Toast.Add.error(t("bot.schedules.errors.Cron end time is required."));
                triggersMapRef.current.endAt?.focus();
                return;
            }
        }

        setIsValidating(true);

        const promise = rescheduleBotCronMutateAsync({
            interval: valuesMapRef.current.interval,
            scope: target,
            running_type: valuesMapRef.current.runningType,
            start_at: valuesMapRef.current.startAt,
            end_at: valuesMapRef.current.endAt,
        });

        Toast.Add.promise(promise, {
            loading: t("bot.schedules.Rescheduling..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Bot rescheduled successfully.");
            },
            finally: () => {
                scheduleDraftSync.updateMeta(null);
                scheduleDraftSync.updateValue(serializeBotScheduleDraft(valuesMapRef.current));
                editStartedAtRef.current = 0;
                setIsValidating(false);
                setIsOpened(false);
            },
        });
    };

    return (
        <Popover.Root modal open={isOpened} onOpenChange={changeOpenedState}>
            <Popover.Trigger asChild>
                <Button size="sm" variant={variant} disabled={isValidating} className={className}>
                    {t("bot.schedules.Reschedule")}
                </Button>
            </Popover.Trigger>
            <Popover.Content className="w-auto min-w-0 max-w-xs sm:max-w-sm md:max-w-md lg:max-w-lg">
                <BotScheduleListItemForm
                    initialValuesMap={syncedValuesMap}
                    valuesMapRef={valuesMapRef}
                    triggersMapRef={triggersMapRef}
                    remoteControlMeta={remoteControlMeta}
                    onValuesChange={syncValuesMap}
                    disabled={isValidating}
                />
                <Flex items="center" justify="end" gap="1" mt="2">
                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => changeOpenedState(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <SubmitButton type="button" size="sm" onClick={createSchedule} isValidating={isValidating}>
                        {t("common.Save")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

export default BotScheduleListItemEdit;
