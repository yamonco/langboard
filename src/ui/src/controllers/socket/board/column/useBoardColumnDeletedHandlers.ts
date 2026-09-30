import { SocketEvents } from "@langboard/core/constants";
import { deleteProjectColumnModel } from "@/core/helpers/ModelHelper";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectColumn } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IBoardColumnDeletedRawResponse {
    uid: string;
    archive_column_uid: string;
    archive_column_name: string;
    archived_at: string;
    count_all_cards_in_column: number;
    count_work_cards_in_column?: number;
}

export interface IUseBoardColumnDeletedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    column: ProjectColumn.TModel;
}

const useBoardColumnDeletedHandlers = ({ callback, column }: IUseBoardColumnDeletedHandlersProps) => {
    return useSocketHandler<{}, IBoardColumnDeletedRawResponse>({
        topic: ESocketTopic.Board,
        topicId: column.project_uid,
        eventKey: `board-column-deleted-${column.project_uid}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.COLUMN.DELETED,
            params: { uid: column.uid },
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

export default useBoardColumnDeletedHandlers;
