import Button from "@/components/base/Button";
import DateTimePicker from "@/components/base/DateTimePicker";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Select from "@/components/base/Select";
import CollaborativeControlOverlay from "@/components/Collaborative/ControlOverlay";
import type { ICollaborativeTextMeta } from "@/components/Collaborative/useCollaborativeText";
import { IBotScheduleFormMap } from "@/components/bots/BotScheduleList/Provider";
import Cron from "@/components/Cron";
import { BaseBotScheduleModel } from "@/core/models";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBotScheduleTriggersMap {
    startAt?: HTMLButtonElement | null;
    endAt?: HTMLButtonElement | null;
}

export interface IBotScheduleControlMeta {
    field: string;
    label: string;
    updatedAt: number;
}

export interface IBotScheduleListItemFormProps {
    initialValuesMap?: IBotScheduleFormMap;
    valuesMapRef: React.RefObject<IBotScheduleFormMap>;
    triggersMapRef: React.RefObject<IBotScheduleTriggersMap>;
    remoteControlMeta?: Record<string, ICollaborativeTextMeta<IBotScheduleControlMeta>>;
    onValuesChange?: (nextValuesMap: IBotScheduleFormMap, field: string, label: string) => void;
    disabled?: bool;
}

function BotScheduleListItemForm({
    initialValuesMap,
    valuesMapRef,
    triggersMapRef,
    remoteControlMeta,
    onValuesChange,
    disabled,
}: IBotScheduleListItemFormProps): React.JSX.Element {
    const [t] = useTranslation();
    const [runningType, setRunningType] = useState(initialValuesMap?.runningType ?? BaseBotScheduleModel.ERunningType.Infinite);
    const [startAt, setStartAt] = useState(initialValuesMap?.startAt);
    const [endAt, setEndAt] = useState(initialValuesMap?.endAt);
    useEffect(() => {
        const nextRunningType = initialValuesMap?.runningType ?? BaseBotScheduleModel.ERunningType.Infinite;
        valuesMapRef.current = {
            runningType: nextRunningType,
            interval: initialValuesMap?.interval,
            startAt: initialValuesMap?.startAt,
            endAt: initialValuesMap?.endAt,
        };
        setRunningType(nextRunningType);
        setStartAt(initialValuesMap?.startAt);
        setEndAt(initialValuesMap?.endAt);
    }, [initialValuesMap?.runningType, initialValuesMap?.interval, initialValuesMap?.startAt, initialValuesMap?.endAt]);
    const onClickSetDateTime = useCallback(
        (e: React.MouseEvent<HTMLButtonElement>) => {
            const pickerType = e.currentTarget.getAttribute("data-picker-type");
            if (pickerType !== "end") {
                return;
            }

            if (!startAt) {
                e.preventDefault();
                e.stopPropagation();
                triggersMapRef.current.startAt?.click();
            }
        },
        [startAt]
    );
    const lastValueCronStringRef = useRef<string>(undefined);
    const syncValuesMap = (field: string, label: string) => {
        onValuesChange?.({ ...valuesMapRef.current }, field, label);
    };
    const renderControlOverlay = (field: string) => {
        const meta = remoteControlMeta?.[field];
        if (!meta) {
            return null;
        }

        return (
            <CollaborativeControlOverlay
                color={meta.color}
                labelClassName="absolute right-2 z-[9999] max-w-32 truncate"
                labelStyle={{ top: "-0.75rem" }}
                name={meta.name}
                title={t("common.User changed field", { name: meta.name, field: meta.value.label })}
            />
        );
    };
    const renderControlFrame = (field: string, children: ReactNode) => {
        return (
            <div className="relative">
                {children}
                {renderControlOverlay(field)}
            </div>
        );
    };

    const onChangeRunningType = (value: BaseBotScheduleModel.ERunningType) => {
        if (valuesMapRef.current.runningType === BaseBotScheduleModel.ERunningType.Onetime && lastValueCronStringRef.current) {
            valuesMapRef.current.interval = lastValueCronStringRef.current;
        }

        setRunningType(value);
        valuesMapRef.current.runningType = value;
        const now = new Date();

        if (BaseBotScheduleModel.RUNNING_TYPES_WITH_START_AT.includes(value)) {
            valuesMapRef.current.startAt = new Date(now.setMinutes(now.getMinutes()));
        } else {
            valuesMapRef.current.startAt = undefined;
        }

        if (BaseBotScheduleModel.RUNNING_TYPES_WITH_END_AT.includes(value)) {
            valuesMapRef.current.endAt = new Date(now.setMinutes(now.getMinutes() + 1));
        } else {
            valuesMapRef.current.endAt = undefined;
        }

        valuesMapRef.current.startAt?.setSeconds(0);
        valuesMapRef.current.endAt?.setSeconds(0);

        setStartAt(valuesMapRef.current.startAt);
        setEndAt(valuesMapRef.current.endAt);

        if (value === BaseBotScheduleModel.ERunningType.Onetime) {
            lastValueCronStringRef.current = valuesMapRef.current.interval;
            valuesMapRef.current.interval = "* * * * *";
        }

        syncValuesMap("running_type", t("bot.Select running type"));
    };

    const onChangeCron = (value: string) => {
        valuesMapRef.current.interval = value;
        syncValuesMap("interval_str", t("bot.schedules.cronHeaders.Interval"));
    };

    const handleChangeStartAtDate = (date: Date | undefined) => {
        date?.setSeconds(0);
        setStartAt(date);
        if (valuesMapRef.current.endAt && valuesMapRef.current.endAt.getTime() < (date?.getTime() ?? 0)) {
            setEndAt(date ? new Date(date.getTime() + 60 * 1000) : undefined);
        }
        setTimeout(() => {
            if (BaseBotScheduleModel.RUNNING_TYPES_WITH_END_AT.includes(runningType)) {
                triggersMapRef.current.endAt?.click();
            }
        }, 0);
        valuesMapRef.current.startAt = date;
        if (valuesMapRef.current.endAt && valuesMapRef.current.endAt.getTime() < (date?.getTime() ?? 0)) {
            valuesMapRef.current.endAt = date ? new Date(date.getTime() + 60 * 1000) : undefined;
        }
        syncValuesMap("start_at", t("bot.schedules.cronHeaders.Start at"));
    };

    const handleChangeEndAtDate = (date: Date | undefined) => {
        date?.setSeconds(0);
        setEndAt(date);
        valuesMapRef.current.endAt = date;
        syncValuesMap("end_at", t("bot.schedules.cronHeaders.End at"));
    };

    return (
        <Flex direction="col" gap="2">
            {renderControlFrame(
                "running_type",
                <Floating.LabelSelect
                    label={t("bot.Select running type")}
                    value={runningType}
                    onValueChange={onChangeRunningType}
                    disabled={disabled}
                    className="w-full"
                    options={Object.keys(BaseBotScheduleModel.ERunningType).map((type) => {
                        const runningType = BaseBotScheduleModel.ERunningType[type];
                        return (
                            <Select.Item key={runningType} value={runningType}>
                                {t(`bot.schedules.cronRunningTypes.${runningType}`)}
                            </Select.Item>
                        );
                    })}
                />
            )}
            {BaseBotScheduleModel.RUNNING_TYPES_WITH_START_AT.includes(runningType) &&
                renderControlFrame(
                    "start_at",
                    <DateTimePicker
                        value={startAt}
                        min={new Date(new Date().setMinutes(new Date().getMinutes()))}
                        onChange={handleChangeStartAtDate}
                        timePicker={{
                            hour: true,
                            minute: true,
                            second: false,
                        }}
                        renderTrigger={() => (
                            <Button
                                type="button"
                                variant={startAt ? "default" : "outline"}
                                className={cn("h-8 gap-2 px-3 lg:h-10", startAt && "rounded-r-none")}
                                title={t("bot.schedules.Set start time")}
                                data-picker-type="start"
                                onClick={onClickSetDateTime}
                                ref={(elem) => {
                                    triggersMapRef.current.startAt = elem;
                                }}
                            >
                                <IconComponent icon="calendar" size="4" />
                                {startAt ? Utils.String.formatDateLocale(startAt) : t("bot.schedules.Set start time")}
                            </Button>
                        )}
                    />
                )}
            {BaseBotScheduleModel.RUNNING_TYPES_WITH_END_AT.includes(runningType) &&
                renderControlFrame(
                    "end_at",
                    <DateTimePicker
                        value={endAt}
                        min={startAt ? new Date(startAt!.getTime() + 60 * 1000) : undefined}
                        onChange={handleChangeEndAtDate}
                        timePicker={{
                            hour: true,
                            minute: true,
                            second: false,
                        }}
                        renderTrigger={() => (
                            <Button
                                type="button"
                                variant={endAt ? "default" : "outline"}
                                className={cn("h-8 gap-2 px-3 lg:h-10", endAt && "rounded-r-none")}
                                title={t("bot.schedules.Set end time")}
                                data-picker-type="end"
                                onClick={onClickSetDateTime}
                                ref={(elem) => {
                                    triggersMapRef.current.endAt = elem;
                                }}
                            >
                                <IconComponent icon="calendar" size="4" />
                                {endAt ? Utils.String.formatDateLocale(endAt) : t("bot.schedules.Set end time")}
                            </Button>
                        )}
                    />
                )}
            {runningType !== BaseBotScheduleModel.ERunningType.Onetime && (
                <div className="relative">
                    <Cron value={initialValuesMap?.interval ?? "@reboot"} setValue={onChangeCron} disabled={disabled} readOnly={disabled} />
                    {renderControlOverlay("interval_str")}
                </div>
            )}
        </Flex>
    );
}

export default BotScheduleListItemForm;
