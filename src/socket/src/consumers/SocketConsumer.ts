import Consumer from "@/core/broadcast/Consumer";
import Subscription from "@/core/server/Subscription";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";

type TSocketPublishQueueData = {
    data: Record<string, unknown>;
    publish_models: TNotificationPublishData[] | TNotificationPublishData;
};

type TNotificationPublishData = {
    topic: string;
    topic_id: string;
    event: string;
    data_keys?: string | string[];
    custom_data?: Record<string, unknown>;
};

Consumer.register(
    "socket_publish",
    async (data: unknown) => {
        if (!Utils.Type.isObject<TSocketPublishQueueData>(data) || !data.data || !data.publish_models) {
            return;
        }

        const model = data.data;

        if (!Utils.Type.isArray(data.publish_models)) {
            data.publish_models = [data.publish_models];
        }

        const publishModels = data.publish_models;
        for (let i = 0; i < publishModels.length; ++i) {
            const publishData: Record<string, unknown> = {};
            const publishModel = publishModels[i];

            if (publishModel.data_keys) {
                if (!Utils.Type.isArray(publishModel.data_keys)) {
                    publishModel.data_keys = [publishModel.data_keys];
                }

                for (let i = 0; i < publishModel.data_keys.length; ++i) {
                    const key = publishModel.data_keys[i];
                    if (!Utils.Type.isUndefined(model[key])) {
                        publishData[key] = model[key];
                    }
                }
            }

            if (publishModel.custom_data) {
                Object.assign(publishData, publishModel.custom_data);
            }

            await Subscription.publish(
                Utils.String.convertSafeEnum(ESocketTopic, publishModel.topic),
                publishModel.topic_id,
                publishModel.event,
                publishData
            );
        }
    },
    "fanout"
);
