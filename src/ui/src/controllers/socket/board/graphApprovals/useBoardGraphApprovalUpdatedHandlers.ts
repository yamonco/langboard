import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ChatMessageModel, GraphApprovalRequestModel } from "@/core/models";
import { EGraphApprovalOriginType, EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";

export interface IBoardGraphApprovalUpdatedRawResponse {
    approval: GraphApprovalRequestModel.Interface;
}

export interface IUseBoardGraphApprovalUpdatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

const useBoardGraphApprovalUpdatedHandlers = ({ callback, projectUID }: IUseBoardGraphApprovalUpdatedHandlersProps) => {
    return useSocketHandler<{}, IBoardGraphApprovalUpdatedRawResponse>({
        topic: ESocketTopic.BoardSettings,
        topicId: projectUID,
        eventKey: `board-graph-approval-updated-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.GRAPH_APPROVAL.UPDATED,
            callback,
            responseConverter: (data) => {
                if (data.approval.status === EGraphApprovalStatus.Pending) {
                    GraphApprovalRequestModel.Model.fromOne(data.approval, true);
                } else {
                    const approval = data.approval;
                    const chatMessage =
                        approval.origin_type === EGraphApprovalOriginType.Chat && approval.chat_history_uid
                            ? ChatMessageModel.Model.getModel(approval.chat_history_uid)
                            : undefined;
                    const interrupt = chatMessage?.message.graph_interrupt;
                    const value = Utils.Type.isObject<Record<string, unknown>>(interrupt?.value) ? interrupt.value : interrupt;
                    if (
                        chatMessage &&
                        interrupt &&
                        Utils.Type.isObject<Record<string, unknown>>(value) &&
                        value.approval_uid === approval.uid &&
                        value.thread_id === approval.thread_id
                    ) {
                        chatMessage.message = {
                            ...chatMessage.message,
                            graph_interrupt: {
                                ...interrupt,
                                value: {
                                    ...value,
                                    status: approval.status,
                                    resolved_by_user_uid: approval.resolved_by_user_uid,
                                    rejection_reason: approval.rejection_reason,
                                },
                            },
                            graph_resume_error: null,
                        };
                    }
                    GraphApprovalRequestModel.Model.deleteModel(data.approval.uid);
                }
                return {};
            },
        },
    });
};

export default useBoardGraphApprovalUpdatedHandlers;
