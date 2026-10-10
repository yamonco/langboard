import { SocketEvents } from "@langboard/core/constants";
import { deleteProjectColumnModel } from "@/core/helpers/ModelHelper";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { Project } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IDashboardProjectColumnDeletedRawResponse {
    uid: string;
    archive_column_uid: string;
    archive_column_name: string;
    archived_at: string;
    count_all_cards_in_column: number;
    count_work_cards_in_column?: number;
}

export interface IUseDashboardProjectColumnDeletedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    project: Project.TModel;
}

const useDashboardProjectColumnDeletedHandlers = ({ callback, project }: IUseDashboardProjectColumnDeletedHandlersProps) => {
    return useSocketHandler<{}, IDashboardProjectColumnDeletedRawResponse>({
        topic: ESocketTopic.Dashboard,
        topicId: project.uid,
        eventKey: `dashboard-project-column-deleted-${project.uid}`,
        onProps: {
            name: SocketEvents.SERVER.DASHBOARD.PROJECT.COLUMN.DELETED,
            params: { uid: project.uid },
            callback,
            responseConverter: (data) => {
                deleteProjectColumnModel(data.uid, {
                    uid: data.archive_column_uid,
                    name: data.archive_column_name,
                    archivedAt: new Date(data.archived_at),
                    sourceCount: data.count_all_cards_in_column,
                    sourceWorkCount: data.count_work_cards_in_column,
                });

                return {};
            },
        },
    });
};

export default useDashboardProjectColumnDeletedHandlers;
