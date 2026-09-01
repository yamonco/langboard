import ISocketClient from "@/core/server/ISocketClient";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";

export interface IValidatorContext {
    client: ISocketClient;
    topicId: string;
}

class _Subscription {
    #subscriptions: Map<string, Map<string, Set<ISocketClient>>>;
    #validators: Map<string, (context: IValidatorContext) => Promise<bool>>;

    constructor() {
        this.#subscriptions = new Map();
        this.#validators = new Map();
    }

    public registerValidator(topic: ESocketTopic | string, validator: (context: IValidatorContext) => Promise<bool>): void {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        this.#validators.set(topic, validator);
    }

    public async validate(topic: ESocketTopic | string, context: IValidatorContext): Promise<bool> {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        const validator = this.#validators.get(topic);
        if (!validator) {
            return true;
        }

        return await validator(context);
    }

    public async publish(topic: ESocketTopic | string, topicId: string, event: string, data: Record<string, unknown>) {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        const subscriptions = this.#subscriptions.get(topic);
        if (!subscriptions) {
            return;
        }

        const subscriberSet = subscriptions.get(topicId);
        if (!subscriberSet) {
            return;
        }
        const subscribers = subscriberSet;

        const arraySubscribers = Array.from(subscribers);
        for (let i = 0; i < arraySubscribers.length; ++i) {
            const subscriber = arraySubscribers[i];

            subscriber.send({
                event,
                topic,
                topic_id: topicId,
                data,
            });
        }
    }

    public async subscribe(ws: ISocketClient, topic: ESocketTopic | string, topicIds: string | string[]) {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        if (!this.#subscriptions.has(topic)) {
            this.#subscriptions.set(topic, new Map());
        }

        const subscriptions = this.#subscriptions.get(topic)!;

        topicIds = Utils.Type.isArray(topicIds) ? topicIds : [topicIds];
        const subscribedIDs: string[] = [];
        for (let i = 0; i < topicIds.length; ++i) {
            const topicId = topicIds[i];
            if (!Utils.Type.isString(topicId) || !topicId.length) {
                continue;
            }

            if (!(await this.validate(topic, { client: ws, topicId }))) {
                continue;
            }

            if (!subscriptions.has(topicId)) {
                subscriptions.set(topicId, new Set());
            }

            const subscribers = subscriptions.get(topicId)!;

            subscribers.add(ws);
            subscribedIDs.push(topicId);
        }

        ws.send({
            event: "subscribed",
            topic,
            topic_id: subscribedIDs,
        });
    }

    public async unsubscribe(ws: ISocketClient, topic: ESocketTopic | string, topicIds: string | string[]) {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        const subscriptions = this.#subscriptions.get(topic);
        if (!subscriptions) {
            return;
        }

        topicIds = Utils.Type.isArray(topicIds) ? topicIds : [topicIds];
        for (let i = 0; i < topicIds.length; ++i) {
            this.#deleteSubscriber(subscriptions, topicIds[i], ws);
        }

        if (!subscriptions.size) {
            this.#subscriptions.delete(topic);
        }

        ws.send({
            event: "unsubscribed",
            topic,
            topic_id: topicIds,
        });
    }

    public unsubscribeAll(ws: ISocketClient) {
        const topics = Array.from(this.#subscriptions.keys());
        for (let i = 0; i < topics.length; ++i) {
            const topic = topics[i];
            const subscriptions = this.#subscriptions.get(topic);
            if (!subscriptions) {
                continue;
            }

            const topicIds = Array.from(subscriptions.keys());
            for (let j = 0; j < topicIds.length; ++j) {
                this.#deleteSubscriber(subscriptions, topicIds[j], ws);
            }

            if (!subscriptions.size) {
                this.#subscriptions.delete(topic);
            }
        }
    }

    #deleteSubscriber(subscriptions: Map<string, Set<ISocketClient>>, topicId: string, ws: ISocketClient): void {
        const subscribers = subscriptions.get(topicId);
        if (!subscribers) {
            return;
        }

        subscribers.delete(ws);
        if (!subscribers.size) {
            subscriptions.delete(topicId);
        }
    }
}

const Subscription = new _Subscription();

export default Subscription;
