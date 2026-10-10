import Button from "@/components/base/Button";
import Table from "@/components/base/Table";
import DateDistance from "@/components/DateDistance";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ProjectCard, ProjectCheckitem } from "@/core/models";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import { add as addDate, differenceInSeconds, intervalToDuration } from "date-fns";
import { useEffect, useMemo, useReducer, useRef } from "react";
import { useTranslation } from "react-i18next";

export interface ITrackingRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
    checkitem: ProjectCheckitem.TModel;
}

function TrackingRow({ checkitem, className, ...props }: ITrackingRowProps): React.JSX.Element | null {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const projectUIDRef = useRef("");
    const title = checkitem.useField("title");
    const rawStatus = checkitem.useField("status");
    const startedAt = checkitem.useField("initial_timer_started_at");
    const isChecked = checkitem.useField("is_checked");
    let status;
    switch (rawStatus) {
        case ProjectCheckitem.ECheckitemStatus.Started:
            status = t("dashboard.Started");
            break;
        case ProjectCheckitem.ECheckitemStatus.Paused:
            status = t("dashboard.Paused");
            break;
        default:
            status = t("dashboard.Stopped");
            break;
    }

    return (
        <Table.FlexRow
            {...props}
            className={cn(
                isChecked &&
                    cn(
                        "text-muted-foreground [&_button]:text-primary/70",
                        "after:absolute after:left-0 after:top-1/2 after:z-50 after:-translate-y-1/2",
                        "after:h-px after:w-full after:bg-border"
                    ),
                className
            )}
        >
            <ModelRegistry.ProjectCheckitem.Provider model={checkitem}>
                <Table.FlexCell className="w-1/4 text-center">
                    <Button
                        variant="link"
                        className="size-auto p-0"
                        onClick={() => navigate(ROUTES.BOARD.CARD(projectUIDRef.current, checkitem.card_uid))}
                    >
                        {title}
                    </Button>
                </Table.FlexCell>
                <Table.FlexCell className="w-1/4 text-center">
                    <TrackingRowCardTitle projectUIDRef={projectUIDRef} />
                </Table.FlexCell>
                <Table.FlexCell className="w-1/6 text-center">{status}</Table.FlexCell>
                <Table.FlexCell className="w-1/6 text-center">{startedAt && <DateDistance date={startedAt} />}</Table.FlexCell>
                <Table.FlexCell className="w-1/6 text-center">
                    <TrackingRowTimeTaken />
                </Table.FlexCell>
            </ModelRegistry.ProjectCheckitem.Provider>
        </Table.FlexRow>
    );
}

interface ITrackingRowCardTitleProps {
    projectUIDRef: React.RefObject<string>;
}

function TrackingRowCardTitle({ projectUIDRef }: ITrackingRowCardTitleProps) {
    const navigate = usePageNavigateRef();
    const { model: checkitem } = ModelRegistry.ProjectCheckitem.useContext();
    const card = ProjectCard.Model.getModel(checkitem.card_uid)!;
    const title = card.useField("title");

    projectUIDRef.current = card.project_uid;

    return (
        <Button variant="link" className="size-auto p-0" onClick={() => navigate(ROUTES.BOARD.CARD(card.project_uid, card.uid))}>
            {title}
        </Button>
    );
}

function TrackingRowTimeTaken() {
    useTranslation();
    const { model: checkitem } = ModelRegistry.ProjectCheckitem.useContext();
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

    return <>{Utils.String.formatTimerDuration(duration)}</>;
}

export default TrackingRow;
