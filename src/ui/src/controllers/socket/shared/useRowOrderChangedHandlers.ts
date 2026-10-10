import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { ProjectCard, ProjectCheckitem } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import { isModel } from "@/core/models/ModelRegistry";

interface IBaseRowOrderChangedResponse {
    move_type: "to_column" | "in_column" | "from_column";
    column_uid?: string;
    uid: string;
    order: number;
    updated_at?: string;
}

interface IInColumnRowOrderChangedResponse extends IBaseRowOrderChangedResponse {
    move_type: "in_column";
    column_uid?: never;
}

interface IRemovedColumnRowOrderChangedResponse extends IBaseRowOrderChangedResponse {
    move_type: "from_column";
    column_uid: string;
}

interface IMovedColumnRowOrderChangedResponse extends IBaseRowOrderChangedResponse {
    move_type: "to_column";
    column_uid: string;
}

export type TRowOrderChangedResponse = IInColumnRowOrderChangedResponse | IRemovedColumnRowOrderChangedResponse | IMovedColumnRowOrderChangedResponse;

export interface IUseRowOrderChangedHandlersProps extends IBaseUseSocketHandlersProps<TRowOrderChangedResponse> {
    type: "ProjectCard" | "ProjectCheckitem";
    params?: Record<string, string>;
    topicId: string;
}

const ROW_ORDER_CHANGED_CONFIG = {
    ProjectCard: {
        onEventName: SocketEvents.SERVER.BOARD.CARD.ORDER_CHANGED,
        targetModel: ProjectCard.Model,
        targetModelColumn: "project_column_uid",
        topic: ESocketTopic.Board,
    },
    ProjectCheckitem: {
        onEventName: SocketEvents.SERVER.BOARD.CARD.CHECKITEM.ORDER_CHANGED,
        targetModel: ProjectCheckitem.Model,
        targetModelColumn: "checklist_uid",
        topic: ESocketTopic.BoardCard,
    },
} as const;

const useRowOrderChangedHandlers = ({ callback, type, params, topicId }: IUseRowOrderChangedHandlersProps) => {
    const { onEventName, targetModel, targetModelColumn, topic } = ROW_ORDER_CHANGED_CONFIG[type];
    const sendEventName = "";

    return useSocketHandler({
        topic,
        topicId,
        eventKey: `${new Utils.String.Case(type).toKebab()}-row-order-changed`,
        onProps: {
            name: onEventName,
            params,
            callback,
            responseConverter: (data) => {
                if (data.move_type === "from_column") {
                    return data;
                }

                const model = targetModel.getModel(data.uid);
                if (model) {
                    model.order = data.order;
                    if (data.updated_at && isModel(model, "ProjectCard")) {
                        model.updated_at = data.updated_at;
                    }
                    if (data.move_type === "to_column") {
                        model[targetModelColumn as "uid"] = data.column_uid;
                    }

                    if (data.move_type !== "in_column" && isModel(model, "ProjectCard")) {
                        model.archived_at = (data as unknown as Record<string, Date>).archived_at;
                    }
                }
                return data;
            },
        },
        sendProps: {
            name: sendEventName,
        },
    });
};

export default useRowOrderChangedHandlers;
