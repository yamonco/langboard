import ISocketClient from "@/core/server/ISocketClient";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import { resolveCardAudience } from "@/core/helpers/CardAudience";

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

    public async publish(topic: ESocketTopic | string, topicId: string, event: string, data: Record<string, unknown>, cardUIDs?: string[]) {
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
        const references = [...(cardUIDs ?? [])];
        if (topic === ESocketTopic.BoardCard) references.push(topicId);
        const card = data.card as { uid?: unknown } | undefined;
        if (card && typeof card.uid === "string") references.push(card.uid);
        const protectedEvent = references.length > 0 || /^(board:card:|dashboard:(card|checkitem):)/.test(event);
        const removal = /^(board|dashboard):card:deleted:/.test(event);
        const allowed = protectedEvent ? await resolveCardAudience(arraySubscribers, references, removal ? "remove" : "read") : new Set<string>();
        const deliveredData = removal
            ? Object.fromEntries(Object.entries(data).filter(([key]) => ["uid", "project_column_uid", "source_type"].includes(key)))
            : data;
        for (let i = 0; i < arraySubscribers.length; ++i) {
            const subscriber = arraySubscribers[i];
            if (protectedEvent && !allowed.has(subscriber.user.uid)) continue;

            subscriber.send({
                event,
                topic,
                topic_id: topicId,
                data: deliveredData,
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
