import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectColumn } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";

interface Props extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

const useBoardColumnWorkflowStageChangedHandlers = ({ callback, projectUID }: Props) => {
    return useSocketHandler<
        {},
        { uid: string; workflow_stage: ProjectColumn.Interface["workflow_stage"]; workflow_counts_as_completed?: boolean | null }
    >({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-column-workflow-stage-changed-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.COLUMN.WORKFLOW_STAGE_CHANGED,
            params: { uid: projectUID },
            callback,
            responseConverter: (data) => {
                const column = ProjectColumn.Model.getModel(data.uid);
                if (column) {
                    column.workflow_stage = data.workflow_stage ?? null;
                    column.workflow_counts_as_completed = data.workflow_counts_as_completed ?? null;
                }
                return {};
            },
        },
    });
};

export default useBoardColumnWorkflowStageChangedHandlers;
