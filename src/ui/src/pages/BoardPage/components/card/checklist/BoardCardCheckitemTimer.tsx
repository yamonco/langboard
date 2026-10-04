import { memo, useEffect, useMemo, useReducer } from "react";
import { add as addDate, intervalToDuration, differenceInSeconds } from "date-fns";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Toast from "@/components/base/Toast";
import { ProjectCheckitem } from "@/core/models";
import { useTranslation } from "react-i18next";
import { Utils } from "@langboard/core/utils";
import useChangeCardCheckitemStatus from "@/controllers/api/card/checkitem/useChangeCardCheckitemStatus";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { IBoardCardCheckRelatedContextParams } from "@/pages/BoardPage/components/card/checklist/types";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";

const BoardCardCheckitemTimer = memo(() => {
    const { model: checkitem } = ModelRegistry.ProjectCheckitem.useContext();
    const [t] = useTranslation();
    const status = checkitem.useField("status");
    const accumulatedSeconds = checkitem.useField("accumulated_seconds");
    const timerStartedAt = checkitem.useField("timer_started_at");
    const [updated, forceUpdate] = useReducer((x) => x + 1, 0);
    const duration = useMemo(() => {
        const now = new Date();
        let timerSeconds = accumulatedSeconds;
        if (status === ProjectCheckitem.ECheckitemStatus.Started && timerStartedAt) {
            timerSeconds += differenceInSeconds(now, timerStartedAt);
        }

        return intervalToDuration({
            start: now,
            end: addDate(now, { seconds: timerSeconds }),
        });
    }, [updated]);

    useEffect(() => {
        let timerTimeout: NodeJS.Timeout | undefined;

        const updateTimer = () => {
            clearTimeout(timerTimeout);
            timerTimeout = undefined;

            let nextMs = 1000;

            if (status === ProjectCheckitem.ECheckitemStatus.Started && timerStartedAt) {
                const startDate = new Date(timerStartedAt);
                const diff = new Date(new Date().getTime() - startDate.getTime()).getMilliseconds();
                nextMs = 1000 + startDate.getMilliseconds() - diff;
                forceUpdate();
            }

            timerTimeout = setTimeout(updateTimer, nextMs);
        };

        updateTimer();

        return () => {
            clearTimeout(timerTimeout);
            timerTimeout = undefined;
        };
    }, [status]);

    return (
        <Popover.Root>
            <Popover.Trigger asChild>
                <Button variant="ghost" size="sm" className="gap-2 px-2" title={t("card.Manage timer")} aria-label={t("card.Manage timer")}>
                    {(!!accumulatedSeconds || status === ProjectCheckitem.ECheckitemStatus.Started) && (
                        <Box textSize={{ initial: "xs", sm: "sm" }}>{Utils.String.formatTimerDuration(duration)}</Box>
                    )}
                    <IconComponent icon="hammer" size="4" />
                </Button>
            </Popover.Trigger>
            <Popover.Content align="end" className="w-auto p-0">
                <BoardCardCheckitemTimerManager />
            </Popover.Content>
        </Popover.Root>
    );
});

function BoardCardCheckitemTimerManager() {
    const { projectUID, card } = useBoardCard();
    const { model: checkitem, params } = ModelRegistry.ProjectCheckitem.useContext<IBoardCardCheckRelatedContextParams>();
    const { isValidating, setIsValidating } = params;
    const [t] = useTranslation();
    const status = checkitem.useField("status");
    const { mutateAsync: changeCheckitemStatusMutateAsync } = useChangeCardCheckitemStatus({ interceptToast: true });

    const changeStatus = (e: React.MouseEvent<HTMLButtonElement>) => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const newStatus = e.currentTarget.getAttribute("data-value") as ProjectCheckitem.ECheckitemStatus;

        const promise = changeCheckitemStatusMutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
            checkitem_uid: checkitem.uid,
            status: newStatus,
        });

        let timerStatus = "";
        switch (newStatus) {
            case ProjectCheckitem.ECheckitemStatus.Started:
                timerStatus = "started";
                break;
            case ProjectCheckitem.ECheckitemStatus.Paused:
                timerStatus = "paused";
                break;
            case ProjectCheckitem.ECheckitemStatus.Stopped:
                timerStatus = "stopped";
                break;
        }

        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t(`successes.Timer ${timerStatus} successfully.`);
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    return (
        <Flex>
            <Button
                variant="ghost"
                size="icon"
                title={t("card.Start timer")}
                className="rounded-r-none"
                disabled={isValidating || status === ProjectCheckitem.ECheckitemStatus.Started}
                data-value={ProjectCheckitem.ECheckitemStatus.Started}
                onClick={changeStatus}
            >
                <IconComponent icon="play" size="5" />
            </Button>
            <Button
                variant="ghost"
                size="icon"
                title={t("card.Pause timer")}
                className="rounded-none"
                disabled={isValidating || status !== ProjectCheckitem.ECheckitemStatus.Started}
                data-value={ProjectCheckitem.ECheckitemStatus.Paused}
                onClick={changeStatus}
            >
                <IconComponent icon="pause" size="5" />
            </Button>
            <Button
                variant="ghost"
                size="icon"
                title={t("card.Stop timer")}
                className="rounded-l-none"
                disabled={isValidating || status === ProjectCheckitem.ECheckitemStatus.Stopped}
                data-value={ProjectCheckitem.ECheckitemStatus.Stopped}
                onClick={changeStatus}
            >
                <IconComponent icon="circle-stop" size="5" />
            </Button>
        </Flex>
    );
}

export default BoardCardCheckitemTimer;
