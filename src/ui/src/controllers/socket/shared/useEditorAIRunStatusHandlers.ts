import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { EInternalBotRunKind, EInternalBotRunStatus } from "@/core/constants/InternalBotRun";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

export interface IEditorAIRunStatusResult {
    task_id: string;
    status: EInternalBotRunStatus | "error";
    output_text?: string;
    error_message?: string;
    error_code?: string;
}

export interface IEditorAIRunStatusRequest {
    task_id: string;
    project_uid: string;
    kind: EInternalBotRunKind;
}

interface IUseEditorAIRunStatusHandlersProps extends IBaseUseSocketHandlersProps<IEditorAIRunStatusResult> {
    eventKey: string;
}

const useEditorAIRunStatusHandlers = ({ eventKey, callback }: IUseEditorAIRunStatusHandlersProps) => {
    return useSocketHandler<IEditorAIRunStatusResult, IEditorAIRunStatusResult, IEditorAIRunStatusRequest>({
        topic: ESocketTopic.None,
        eventKey,
        onProps: {
            name: SocketEvents.SERVER.BOARD.EDITOR_AI.STATUS_RESULT,
            callback,
        },
        sendProps: {
            name: SocketEvents.CLIENT.BOARD.EDITOR_AI.STATUS,
        },
    });
};

export default useEditorAIRunStatusHandlers;
