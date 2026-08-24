import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import BotScheduleListItemForm, { IBotScheduleTriggersMap } from "@/components/bots/BotScheduleList/ItemForm";
import { IBotScheduleFormMap, useBotScheduleList } from "@/components/bots/BotScheduleList/Provider";
import useScheduleBotCron from "@/controllers/api/shared/botSchedules/useScheduleBotCron";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { BaseBotScheduleModel } from "@/core/models";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

function BotScheduleListItemAddButton(): React.JSX.Element {
    const { bot, params, target, copiedForm, isAddMode, setIsAddMode } = useBotScheduleList();
    const [t] = useTranslation();
    const [isValidating, setIsValidating] = useState(false);
    const projectUID = "project_uid" in target ? target.project_uid : target.uid;
    const { mutateAsync: scheduleBotCronMutateAsync } = useScheduleBotCron(
        { ...params, bot_uid: bot.uid, project_uid: projectUID },
        { interceptToast: true }
    );
    const valuesMapRef = useRef<IBotScheduleFormMap>(copiedForm ?? {});
    const triggersMapRef = useRef<IBotScheduleTriggersMap>({});

    const createCron = () => {
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

        const promise = scheduleBotCronMutateAsync({
            interval: valuesMapRef.current.interval ?? "* * * * *",
            scope: target,
            running_type: valuesMapRef.current.runningType,
            start_at: valuesMapRef.current.startAt,
            end_at: valuesMapRef.current.endAt,
        });

        Toast.Add.promise(promise, {
            loading: t("bot.schedules.Scheduling..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Bot scheduled successfully.");
            },
            finally: () => {
                setIsValidating(false);
                setIsAddMode(false);
            },
        });
    };

    useEffect(() => {
        if (isAddMode) {
            valuesMapRef.current = copiedForm ?? {};
        }
    }, [isAddMode, copiedForm]);

    return (
        <Popover.Root modal open={isAddMode} onOpenChange={setIsAddMode}>
            <Popover.Trigger asChild>
                <Button variant="outline" className="w-full border-2 border-dashed" disabled={isValidating}>
                    {t("bot.schedules.Schedule")}
                </Button>
            </Popover.Trigger>
            <Popover.Content className="w-auto min-w-0 max-w-xs sm:max-w-sm md:max-w-md lg:max-w-lg">
                <BotScheduleListItemForm
                    initialValuesMap={copiedForm}
                    valuesMapRef={valuesMapRef}
                    triggersMapRef={triggersMapRef}
                    disabled={isValidating}
                />
                <Flex items="center" justify="end" gap="1" mt="2">
                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => setIsAddMode(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <SubmitButton type="button" size="sm" onClick={createCron} isValidating={isValidating}>
                        {t("common.Save")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

export default BotScheduleListItemAddButton;
