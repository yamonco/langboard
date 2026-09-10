import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { Project } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";
import { newerProjectActivity } from "@/pages/DashboardPage/components/ProjectActivityPriority";

interface IDashboardProjectActivityRecordedRawResponse {
    last_activity_at: string;
}

export interface IUseDashboardProjectActivityRecordedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    project: Project.TModel;
}

const useDashboardProjectActivityRecordedHandlers = ({ callback, project }: IUseDashboardProjectActivityRecordedHandlersProps) => {
    return useSocketHandler<{}, IDashboardProjectActivityRecordedRawResponse>({
        topic: ESocketTopic.Dashboard,
        topicId: project.uid,
        eventKey: `dashboard-project-activity-recorded-${project.uid}`,
        onProps: {
            name: SocketEvents.SERVER.DASHBOARD.PROJECT.ACTIVITY_RECORDED,
            params: { uid: project.uid },
            callback,
            responseConverter: (data) => {
                const recordedAt = newerProjectActivity(project.last_activity_at, data.last_activity_at);
                if (recordedAt !== project.last_activity_at) {
                    project.last_activity_at = recordedAt;
                }
                return {};
            },
        },
    });
};

export default useDashboardProjectActivityRecordedHandlers;
