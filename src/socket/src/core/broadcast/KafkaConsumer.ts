/* eslint-disable @typescript-eslint/no-explicit-any */
import { BROADCAST_MAX_MESSAGE_BYTES, BROADCAST_URLS, PROJECT_NAME } from "@/Constants";
import BaseConsumer from "@/core/broadcast/BaseConsumer";
import { decodeBrokerEnvelope } from "@/core/broadcast/BrokerEnvelope";
import Cache from "@/core/caching/Cache";
import Logger from "@/core/utils/Logger";
import { Utils } from "@langboard/core/utils";
import { Consumer, Kafka } from "kafkajs";

const BROKER_ENVELOPE_SCHEMA_VERSION = "2";

class KafkaConsumer extends BaseConsumer {
    #client: Kafka;
    #consumer: Consumer | undefined;
    #groupId: string;
    #stopped = false;

    constructor(groupId: string) {
        super();
        this.#groupId = groupId;

        this.#client = new Kafka({
            clientId: `${PROJECT_NAME}-socket`,
            brokers: BROADCAST_URLS,
            retry: {
                retries: Number.MAX_SAFE_INTEGER,
                restartOnFailure: async (error) => {
                    Logger.red("Kafka Client Error", error, "\n");
                    return true;
                },
            },
        });
    }

    public async start() {
        this.#stopped = false;

        while (!this.#stopped) {
            const consumer = this.#client.consumer({
                groupId: this.#groupId,
                allowAutoTopicCreation: true,
                maxBytes: BROADCAST_MAX_MESSAGE_BYTES,
            });
            this.#consumer = consumer;

            try {
                await consumer.connect();
                if (this.#stopped) {
                    await consumer.disconnect().catch(() => undefined);
                    return;
                }

                const topics = this.getEmitterNames();
                await consumer.subscribe({ topics, fromBeginning: true });
                if (this.#stopped) {
                    await consumer.disconnect().catch(() => undefined);
                    return;
                }

                await consumer.run({
                    eachMessage: async ({ topic, message }) => {
                        if (!message.value) {
                            return;
                        }

                        try {
                            const decoder = new TextDecoder("utf-8");
                            const envelope = decodeBrokerEnvelope(
                                Utils.Json.Parse(decoder.decode(message.value)),
                                topic,
                                BROKER_ENVELOPE_SCHEMA_VERSION
                            );
                            if (!envelope) {
                                return;
                            }

                            let data: unknown;
                            if (envelope.type === "inline") {
                                data = envelope.data;
                            } else {
                                data = await Cache.get<Record<string, any>>(envelope.cacheKey);
                                if (!data) {
                                    return;
                                }
                            }

                            await this.emit(topic, data);
                        } catch (error) {
                            Logger.red(`Kafka Consumer: Error processing message on topic ${topic}`, error, "\n");
                            return;
                        }
                    },
                });

                break;
            } catch (error) {
                if (this.#consumer === consumer) {
                    this.#consumer = undefined;
                }
                await consumer.disconnect().catch(() => undefined);
                if (this.#stopped) {
                    return;
                }
                Logger.red("Error starting consumer", error, "\n");
                await new Promise((resolve) => setTimeout(resolve, 5000)); // Retry after 5 seconds
            }
        }
    }

    public async stop() {
        this.#stopped = true;
        const consumer = this.#consumer;
        this.#consumer = undefined;
        await consumer?.disconnect();
    }
}

export default KafkaConsumer;
