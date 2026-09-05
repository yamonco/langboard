import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectColumn } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

interface IDescriptionChangedProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

/** Keep an open board's guidance current without modifying card state. */
const useBoardColumnDescriptionChangedHandlers = ({ callback, projectUID }: IDescriptionChangedProps) => {
    return useSocketHandler<{}, { uid: string; description: string }>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-column-description-changed-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.COLUMN.DESCRIPTION_CHANGED,
            params: { uid: projectUID },
            callback,
            responseConverter: (data) => {
                const column = ProjectColumn.Model.getModel(data.uid);
                if (column) column.description = data.description;
                return {};
            },
        },
    });
};

export default useBoardColumnDescriptionChangedHandlers;
