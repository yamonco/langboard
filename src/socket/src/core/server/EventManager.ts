import SocketClient from "@/core/server/SocketClient";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import Subscription from "@/core/server/Subscription";

export type TEventContext = {
    client: SocketClient;
    data: Record<string, unknown>;
    topicId: string;
};

type TEventCallback = (context: TEventContext) => void | Promise<void>;

class _EventManager {
    #events: Map<string, Partial<Record<ESocketTopic, TEventCallback[]>>>;

    constructor() {
        this.#events = new Map();
    }

    public on(topic: ESocketTopic, event: string, callback: TEventCallback): _EventManager {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        if (!this.#events.has(event)) {
            this.#events.set(event, {});
        }
        if (!this.#events.get(event)![topic]) {
            this.#events.get(event)![topic] = [];
        }
        this.#events.get(event)![topic]!.push(callback);

        return this;
    }

    public async emit(topic: ESocketTopic | string, event: string, context: TEventContext): Promise<void> {
        const socketTopic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        if (!this.#events.has(event) || !this.#events.get(event)![socketTopic]) {
            return;
        }

        if (socketTopic !== ESocketTopic.None) {
            if (!Utils.Type.isString(context.topicId) || !Subscription.isSubscribed(context.client, socketTopic, context.topicId)) {
                return;
            }
            try {
                if (!(await Subscription.validate(socketTopic, { client: context.client, topicId: context.topicId }))) {
                    return;
                }
            } catch {
                return;
            }
            if (!Subscription.isSubscribed(context.client, socketTopic, context.topicId)) {
                return;
            }
        }

        const callbacks = this.#events.get(event)![socketTopic]!;
        for (let i = 0; i < callbacks.length; ++i) {
            const callback = callbacks[i];

            try {
                await callback(context);
            } catch {
                continue;
            }
        }
    }
}

const EventManager = new _EventManager();

export default EventManager;
