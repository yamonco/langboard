import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectDockSnapshot } from "@/core/models/projectDock";
import applyProjectDockSnapshot from "@/core/helpers/applyProjectDockSnapshot";

interface Props extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

export default function useBoardColumnDockChangedHandlers({ callback, projectUID }: Props) {
    return useSocketHandler<{}, ProjectDockSnapshot>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-column-dock-changed-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.COLUMN.DOCK_CHANGED,
            params: { uid: projectUID },
            callback,
            responseConverter: (data) => {
                applyProjectDockSnapshot(projectUID, data);
                return {};
            },
        },
    });
}
