import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { Project, ProjectCard, ProjectColumn } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IDashboardCardOrderChangedRawResponse {
    uid: string;
    from_column_uid: string;
    to_column_uid: string;
    project_column_name: string;
    archived_at: string;
    source_type?: string | null;
}

export interface IUseDashboardCardOrderChangedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    project: Project.TModel;
}

const useDashboardCardOrderChangedHandlers = ({ callback, project }: IUseDashboardCardOrderChangedHandlersProps) => {
    return useSocketHandler<{}, IDashboardCardOrderChangedRawResponse>({
        topic: ESocketTopic.Dashboard,
        topicId: project.uid,
        eventKey: `dashboard-card-order-changed-${project.uid}`,
        onProps: {
            name: SocketEvents.SERVER.DASHBOARD.CARD.ORDER_CHANGED,
            params: { uid: project.uid },
            callback,
            responseConverter: (data) => {
                const columns = ProjectColumn.Model.getModels(
                    (model) => model.project_uid === project.uid && (model.uid === data.from_column_uid || model.uid === data.to_column_uid)
                );
                if (data.source_type !== "project_wiki" && data.from_column_uid !== data.to_column_uid) {
                    for (let i = 0; i < columns.length; ++i) {
                        if (columns[i].uid === data.from_column_uid) {
                            --columns[i].count;
                        } else if (columns[i].uid === data.to_column_uid) {
                            ++columns[i].count;
                        }
                    }
                }

                const card = ProjectCard.Model.getModel(data.uid);
                if (card) {
                    card.project_column_uid = data.to_column_uid;
                    card.project_column_name = data.project_column_name;
                    card.archived_at = data.archived_at;
                }

                return {};
            },
        },
    });
};

export default useDashboardCardOrderChangedHandlers;
