import { Routing, SocketEvents } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { InternalBotModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";

export interface IInternalBotCreatedRawResponse {
    uid: string;
}

const useInternalBotCreatedHandlers = ({ callback }: IBaseUseSocketHandlersProps<{}>) => {
    return useSocketHandler<{}, IInternalBotCreatedRawResponse>({
        topic: ESocketTopic.Global,
        eventKey: "internal-bot-created",
        onProps: {
            name: SocketEvents.SERVER.GLOBALS.INTERNAL_BOTS.CREATED,
            callback,
            responseConverter: (data) => {
                const url = Utils.String.format(Routing.API.GLOBAL.INTERNAL_BOTS.GET, { bot_uid: data.uid });
                api.get(url, {
                    env: { interceptToast: true } as never,
                }).then((res) => {
                    InternalBotModel.Model.fromOne(res.data.internal_bot, true);
                });
                return {};
            },
        },
    });
};

export default useInternalBotCreatedHandlers;
