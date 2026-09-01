/* eslint-disable @typescript-eslint/no-explicit-any */
import EventManager from "@/core/server/EventManager";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { AI_REQUEST_TIMEOUT, AI_STREAM_MAX_BUFFER_MB, OLLAMA_API_URL } from "@/Constants";
import axios, { isAxiosError } from "axios";
import Subscription from "@/core/server/Subscription";
import Logger from "@/core/utils/Logger";
import Cache from "@/core/caching/Cache";
import { SocketEvents } from "@langboard/core/constants";
import { Readable } from "stream";

const OLLAMA_PULLING_MODELS_CACHE_KEY = "ollama:pulling:models";
const ollamaApi = axios.create({
    baseURL: OLLAMA_API_URL,
    timeout: AI_REQUEST_TIMEOUT * 1000,
});

const setPullingModels = async ({ model, toggle, skipIfExists }: { model: string; toggle: bool; skipIfExists: bool }) => {
    const pullingModels = (await Cache.get<Record<string, bool>>(OLLAMA_PULLING_MODELS_CACHE_KEY)) || {};
    if (skipIfExists && pullingModels[model]) {
        return false;
    }

    if (toggle) {
        pullingModels[model] = true;
    } else {
        delete pullingModels[model];
    }

    await Cache.set(OLLAMA_PULLING_MODELS_CACHE_KEY, pullingModels, 24 * 60 * 60);
    return true;
};

EventManager.on(ESocketTopic.OllamaManager, SocketEvents.CLIENT.SETTINGS.OLLAMA.COPY_MODEL, async ({ topicId, data }) => {
    const model = data.model;
    const copyTo = data.copy_to;
    if (!OLLAMA_API_URL || !Utils.Type.isString(model) || !Utils.Type.isString(copyTo)) {
        return;
    }

    try {
        await ollamaApi.post("/api/copy", { data: { source: model, destination: copyTo } });
        await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_COPIED, { model, copy_to: copyTo });
    } catch (error) {
        Logger.error(error, "\n");
    }
});

EventManager.on(ESocketTopic.OllamaManager, SocketEvents.CLIENT.SETTINGS.OLLAMA.DELETE_MODEL, async ({ topicId, data }) => {
    const model = data.model;
    if (!OLLAMA_API_URL || !Utils.Type.isString(model)) {
        return;
    }

    try {
        await ollamaApi.delete("/api/delete", { data: { model } });
        await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_DELETED, { model });
    } catch (error) {
        Logger.error(error, "\n");
        if (isAxiosError(error)) {
            if (error.status === EHttpStatus.HTTP_404_NOT_FOUND) {
                await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_DELETED, { model });
            }
        }
    }
});

EventManager.on(ESocketTopic.OllamaManager, SocketEvents.CLIENT.SETTINGS.OLLAMA.PULL_MODEL, async ({ topicId, data }) => {
    const model = data.model;
    if (!OLLAMA_API_URL || !Utils.Type.isString(model)) {
        return;
    }

    if (!(await setPullingModels({ model, toggle: true, skipIfExists: true }))) {
        return;
    }

    try {
        const result = await ollamaApi.post<Readable>(
            "/api/pull",
            { model, stream: true },
            {
                responseType: "stream",
            }
        );

        const bufferedChunks: string[] = [];
        let bufferedBytes = 0;
        const textDecoder = new TextDecoder();
        let percent = 0;

        const bufferChunk = (chunk: string) => {
            bufferedBytes += Buffer.byteLength(chunk, "utf-8");
            if (bufferedBytes > AI_STREAM_MAX_BUFFER_MB * 1024 * 1024) {
                throw new Error(`Ollama stream buffer exceeded ${AI_STREAM_MAX_BUFFER_MB} MB`);
            }
            bufferedChunks.push(chunk);
        };

        const clearBuffer = () => {
            bufferedChunks.splice(0);
            bufferedBytes = 0;
        };

        const updatePercent = (jsonData: Record<string, any>) => {
            if (Utils.Type.isNumber(jsonData.total) && Utils.Type.isNumber(jsonData.completed)) {
                percent = Math.floor((jsonData.completed / jsonData.total) * 10000) / 100;
                return true;
            }

            return false;
        };

        const publishChunk = async (jsonChunk: Record<string, any>) => {
            if (updatePercent(jsonChunk)) {
                await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_PULLING_STATUS, {
                    percent,
                    model,
                });
                return;
            }
            await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_PULLING_STATUS, {
                status: jsonChunk.status,
                model,
            });
        };

        try {
            for await (const rawChunk of result.data) {
                const chunkString = textDecoder.decode(rawChunk, { stream: true });
                if (!chunkString.trim()) {
                    continue;
                }

                const splitChunks = chunkString.split("\n");
                for (let i = 0; i < splitChunks.length; ++i) {
                    const chunk = splitChunks[i];
                    if (!chunk) {
                        continue;
                    }
                    if (!chunk.endsWith("}")) {
                        bufferChunk(chunk);
                        continue;
                    }

                    let jsonChunk: Record<string, any>;
                    try {
                        jsonChunk = Utils.Json.Parse(`${bufferedChunks.join("")}${chunk}`);
                    } catch {
                        bufferChunk(chunk);
                        continue;
                    }

                    clearBuffer();
                    await publishChunk(jsonChunk);
                }
            }

            if (bufferedChunks.length) {
                let finalChunk: Record<string, any> | undefined;
                try {
                    finalChunk = Utils.Json.Parse(bufferedChunks.join(""));
                } catch {
                    // Ignore an incomplete final stream chunk.
                }
                if (finalChunk) {
                    await publishChunk(finalChunk);
                }
            }
            await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_PULLING_STATUS, {
                status: "success",
                model,
            });
        } finally {
            clearBuffer();
            if (!result.data.destroyed) {
                result.data.destroy();
            }
        }
    } catch (error) {
        Logger.error(error, "\n");
        await Subscription.publish(ESocketTopic.OllamaManager, topicId, SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_PULLING_STATUS, {
            status: "error",
            model,
            error: (error as Error).message,
        });
    } finally {
        await setPullingModels({ model, toggle: false, skipIfExists: false });
    }
});
