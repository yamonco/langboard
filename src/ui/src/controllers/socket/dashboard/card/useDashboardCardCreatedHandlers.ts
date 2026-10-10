import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { Project, ProjectColumn } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IDashboardCardCreatedRawResponse {
    project_column_uid: string;
    source_type?: string | null;
}

export interface IUseDashboardCardCreatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    project: Project.TModel;
}

const useDashboardCardCreatedHandlers = ({ callback, project }: IUseDashboardCardCreatedHandlersProps) => {
    return useSocketHandler<{}, IDashboardCardCreatedRawResponse>({
        topic: ESocketTopic.Dashboard,
        topicId: project.uid,
        eventKey: `dashboard-card-created-${project.uid}`,
        onProps: {
            name: SocketEvents.SERVER.DASHBOARD.CARD.CREATED,
            params: { uid: project.uid },
            callback,
            responseConverter: (data) => {
                if (data.source_type === "project_wiki") {
                    return {};
                }
                const column = ProjectColumn.Model.getModel((model) => model.uid === data.project_column_uid);
                if (!column) {
                    return {};
                }

                ++column.count;
                return {};
            },
        },
    });
};

export default useDashboardCardCreatedHandlers;
