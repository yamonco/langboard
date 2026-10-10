import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectLabel } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

export interface IBoardLabelDetailsChangedRawResponse {
    name?: string;
    color?: string;
    description?: string;
    global_display?: ProjectLabel.Interface["global_display"];
}

export interface IUseBoardLabelDetailsChangedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
    labelUID: string;
}

const useBoardLabelDetailsChangedHandlers = ({ callback, projectUID, labelUID }: IUseBoardLabelDetailsChangedHandlersProps) => {
    return useSocketHandler<{}, IBoardLabelDetailsChangedRawResponse>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-label-details-changed-${labelUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.LABEL.DETAILS_CHANGED,
            params: { uid: labelUID },
            callback,
            responseConverter: (data) => {
                const label = ProjectLabel.Model.getModel(labelUID);
                if (label) {
                    for (const key of ["name", "color", "description"] as const) {
                        if (data[key] !== undefined) label[key] = data[key];
                    }
                    if ("global_display" in data) label.global_display = data.global_display;
                }
                return {};
            },
        },
    });
};

export default useBoardLabelDetailsChangedHandlers;
