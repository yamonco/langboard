import { SocketEvents } from "@langboard/core/constants";
import { ProjectCheckitem } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";

interface IProgressChangedPayload {
    card_uid: string;
    checkitems?: {
        uid: string;
        is_checked: boolean;
        status: ProjectCheckitem.ECheckitemStatus;
        accumulated_seconds: number;
        timer_started_at?: Date | null;
    }[];
}

interface IProps extends IBaseUseSocketHandlersProps<IProgressChangedPayload> {
    projectUID: string;
    subscriberKey?: string;
}

const useBoardChecklistProgressChangedHandlers = ({ callback, projectUID, subscriberKey }: IProps) =>
    useSocketHandler<IProgressChangedPayload>({
        topic: ESocketTopic.Board,
        topicId: projectUID,
        eventKey: `board-card-checklist-progress-changed-${projectUID}${subscriberKey ? `-${subscriberKey}` : ""}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.CARD.CHECKLIST.PROGRESS_CHANGED,
            params: { uid: projectUID },
            callback,
            responseConverter: (data) => {
                data.checkitems?.forEach(({ uid, ...fields }) => {
                    const checkitem = ProjectCheckitem.Model.getModel(uid);
                    if (checkitem)
                        Object.entries(fields).forEach(([key, value]) => {
                            checkitem[key] = value as never;
                        });
                });
                return data;
            },
        },
    });

export default useBoardChecklistProgressChangedHandlers;
