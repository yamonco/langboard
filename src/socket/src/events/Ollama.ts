import EventManager from "@/core/server/EventManager";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { AI_REQUEST_TIMEOUT, API_INTERNAL_URL, OLLAMA_API_URL } from "@/Constants";
import axios, { isAxiosError } from "axios";
import Subscription from "@/core/server/Subscription";
import Logger from "@/core/utils/Logger";
import { SocketEvents } from "@langboard/core/constants";

const ollamaApi = axios.create({
    baseURL: OLLAMA_API_URL,
    timeout: AI_REQUEST_TIMEOUT * 1000,
});

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

EventManager.on(ESocketTopic.OllamaManager, SocketEvents.CLIENT.SETTINGS.OLLAMA.PULL_MODEL, async ({ client, topicId, data }) => {
    const model = data.model;
    if (!Utils.Type.isString(model) || !model.trim() || model.length > 255) {
        return;
    }

    try {
        await axios.post(
            `${API_INTERNAL_URL}/auth/socket/ollama/models/pull`,
            { model },
            { headers: { Authorization: `Bearer ${client.authorizationToken}` }, timeout: AI_REQUEST_TIMEOUT * 1000 }
        );
    } catch (error) {
        Logger.error(error, "\n");
        client.send({
            event: SocketEvents.SERVER.SETTINGS.OLLAMA.MODEL_PULLING_STATUS,
            topic: ESocketTopic.OllamaManager,
            topic_id: topicId,
            data: { status: "error", model, error: "Pull request could not be confirmed" },
        });
    }
});
