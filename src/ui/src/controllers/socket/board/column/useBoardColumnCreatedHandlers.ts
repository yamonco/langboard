import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { Project, ProjectColumn } from "@/core/models";
import applyProjectDockSnapshot from "@/core/helpers/applyProjectDockSnapshot";
import { ESocketTopic } from "@langboard/core/enums";

export interface IBoardColumnCreatedRawResponse {
    column: ProjectColumn.IStore;
}

export interface IUseBoardColumnCreatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

const useBoardColumnCreatedHandlers = ({ callback, projectUID }: IUseBoardColumnCreatedHandlersProps) => {
    return useSocketHandler<{}, IBoardColumnCreatedRawResponse>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-column-created-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.COLUMN.CREATED,
            params: { uid: projectUID },
            callback,
            responseConverter: (data) => {
                ProjectColumn.Model.fromOne(data.column, true);
                const snapshot = Project.Model.getModel(projectUID)?.latestDockSnapshot;
                if (snapshot) applyProjectDockSnapshot(projectUID, snapshot);
                return {};
            },
        },
    });
};

export default useBoardColumnCreatedHandlers;
