import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

export interface IEditorApprovalResumeResult {
    approval_uid: string;
    status: "completed" | "awaiting_approval" | "claim_failed" | "result_unknown" | "lease_lost";
    output_text?: string;
    error_code?: string;
}

export interface IEditorApprovalResumeRequest {
    approval_uid: string;
    project_uid: string;
    resume: { approved: boolean; rejected: boolean };
}

interface IUseEditorApprovalResumeHandlersProps extends IBaseUseSocketHandlersProps<IEditorApprovalResumeResult> {
    approvalUID: string;
}

const useEditorApprovalResumeHandlers = ({ approvalUID, callback }: IUseEditorApprovalResumeHandlersProps) => {
    return useSocketHandler<IEditorApprovalResumeResult, IEditorApprovalResumeResult, IEditorApprovalResumeRequest>({
        topic: ESocketTopic.None,
        eventKey: `editor-approval-resume-${approvalUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.GRAPH_APPROVAL.RESUME_RESULT,
            callback,
        },
        sendProps: {
            name: SocketEvents.CLIENT.BOARD.EDITOR_APPROVAL_RESUME,
        },
    });
};

export default useEditorApprovalResumeHandlers;
