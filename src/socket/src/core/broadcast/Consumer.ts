import { BROADCAST_NODE_FANOUT_CONSUMER_GROUP, BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP, BROADCAST_TYPE, SOCKET_OWNER } from "@/Constants";
import BaseConsumer from "@/core/broadcast/BaseConsumer";
import InMemoryConsumer from "@/core/broadcast/InMemoryConsumer";
import KafkaConsumer from "@/core/broadcast/KafkaConsumer";

type TConsumerPurpose = "fanout" | "side_effect";

class _Consumer extends BaseConsumer {
    #consumers: Record<TConsumerPurpose, BaseConsumer>;
    #started = false;
    #startPromise: Promise<void> | undefined;

    constructor() {
        super();

        if (BROADCAST_TYPE === "in-memory") {
            const consumer = new InMemoryConsumer();
            this.#consumers = {
                fanout: consumer,
                side_effect: consumer,
            };
        } else if (BROADCAST_TYPE === "kafka") {
            this.#consumers = {
                fanout: new KafkaConsumer(BROADCAST_NODE_FANOUT_CONSUMER_GROUP),
                side_effect: new KafkaConsumer(BROADCAST_NODE_SIDE_EFFECT_CONSUMER_GROUP),
            };
        } else {
            throw new Error(`Unsupported broadcast type: ${BROADCAST_TYPE}`);
        }
    }

    public override register(event: string, emitter: (data: unknown) => Promise<void>, purpose: TConsumerPurpose = "fanout"): void {
        this.#consumers[purpose].register(event, emitter);
    }

    public async start() {
        if (SOCKET_OWNER !== "node") {
            return;
        }

        if (this.#startPromise) {
            await this.#startPromise;
            return;
        }

        const consumers = Array.from(new Set(Object.values(this.#consumers)));
        this.#started = true;
        const startPromise = Promise.all(consumers.map((consumer) => consumer.start()))
            .then(() => undefined)
            .catch(async (error) => {
                await Promise.allSettled(consumers.map((consumer) => consumer.stop()));
                this.#started = false;
                throw error;
            });
        this.#startPromise = startPromise;

        try {
            await startPromise;
        } finally {
            if (this.#startPromise === startPromise) {
                this.#startPromise = undefined;
            }
        }
    }

    public async stop() {
        if (!this.#started && !this.#startPromise) {
            return;
        }

        this.#started = false;
        await Promise.allSettled(Array.from(new Set(Object.values(this.#consumers))).map((consumer) => consumer.stop()));
    }
}

const Consumer = new _Consumer();

export default Consumer;
