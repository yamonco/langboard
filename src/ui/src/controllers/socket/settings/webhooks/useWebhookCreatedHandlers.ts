import { Routing, SocketEvents } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { WebhookModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic, ESettingSocketTopicID } from "@langboard/core/enums";

export interface IWebhookCreatedRawResponse {
    uid: string;
}

const useWebhookCreatedHandlers = ({ callback }: IBaseUseSocketHandlersProps<{}>) => {
    return useSocketHandler<{}, IWebhookCreatedRawResponse>({
        topic: ESocketTopic.AppSettings,
        topicId: ESettingSocketTopicID.Webhook,
        eventKey: "webhook-created",
        onProps: {
            name: SocketEvents.SERVER.SETTINGS.WEBHOOKS.CREATED,
            callback,
            responseConverter: (data) => {
                const url = Utils.String.format(Routing.API.SETTINGS.WEBHOOKS.GET, { webhook_uid: data.uid });
                api.get(url, {
                    env: { interceptToast: true } as never,
                }).then((res) => {
                    WebhookModel.Model.fromOne(res.data.webhook, true);
                });
                return {};
            },
        },
    });
};

export default useWebhookCreatedHandlers;
