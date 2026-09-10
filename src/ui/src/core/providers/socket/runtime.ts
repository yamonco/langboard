import { refresh } from "@/core/helpers/Api";
import { getTopicWithId, ISocketCreateSocketProps, ISocketStore, TEventName } from "@/core/stores/SocketStore";
import { ESocketStatus, ESocketTopic } from "@langboard/core/enums";
import type { TSocketEventKeyMap } from "@/core/stores/socket/types";

interface IRunEventsProps {
    topic?: ESocketTopic;
    topicId?: string;
    eventName: TEventName;
    data?: unknown;
}
type TStreamErrorCallback = ISocketCreateSocketProps<unknown>["onError"];
type TCloseStatusHandler = () => Promise<bool>;

const streamErrorCallbacks: Partial<Record<ESocketTopic, Record<string, TStreamErrorCallback>>> = {};

const isSocketTopic = (value: unknown): value is ESocketTopic => {
    return typeof value === "string" && Object.values<string>(ESocketTopic).includes(value);
};

export const setStreamErrorCallback = (topic: ESocketTopic, event: string, callback: TStreamErrorCallback) => {
    if (!streamErrorCallbacks[topic]) {
        streamErrorCallbacks[topic] = {};
    }

    if (!streamErrorCallbacks[topic][event]) {
        streamErrorCallbacks[topic][event] = callback;
    }
};

export const removeStreamErrorCallback = (topic: ESocketTopic, event: string) => {
    if (streamErrorCallbacks[topic]?.[event]) {
        delete streamErrorCallbacks[topic][event];
    }
};

const runStreamErrorCallbacks = async (event: Event) => {
    const topics = Object.values(ESocketTopic);
    for (let i = 0; i < topics.length; ++i) {
        const topic = topics[i];
        const callbacks = streamErrorCallbacks[topic];

        if (!callbacks) {
            continue;
        }

        const eventNames = Object.keys(callbacks);
        for (let j = 0; j < eventNames.length; ++j) {
            const callback = callbacks[eventNames[j]];
            await callback(event);
        }

        delete streamErrorCallbacks[topic];
    }
};

export interface ICreateSocketRuntimeProps {
    createSocket: ISocketStore["createSocket"];
    getStore: ISocketStore["getStore"];
    closeSocket: ISocketStore["close"];
    getAccessToken: () => string | undefined;
    removeAccessToken: () => void;
    reconnect: () => void;
    shouldReconnect: () => bool;
}

export const createSocketRuntime = ({
    createSocket,
    getStore,
    closeSocket,
    getAccessToken,
    removeAccessToken,
    reconnect,
    shouldReconnect,
}: ICreateSocketRuntimeProps) => {
    const runEventCallbacks = async (eventMap: TSocketEventKeyMap | undefined, data?: unknown) => {
        if (!eventMap) {
            return;
        }

        const eventKeys = Object.keys(eventMap);
        for (let i = 0; i < eventKeys.length; ++i) {
            const callbacks = eventMap[eventKeys[i]];
            if (!callbacks?.length) {
                continue;
            }

            for (let j = 0; j < callbacks.length; ++j) {
                const callback = callbacks[j];
                if (typeof callback === "function") {
                    await callback(data);
                }
            }
        }
    };

    const isDefaultEventName = (eventName: TEventName): eventName is "open" | "close" | "error" => {
        return eventName === "open" || eventName === "close" || eventName === "error";
    };

    const runDefaultEvents = async (eventName: "open" | "close" | "error", data?: unknown) => {
        const socketMap = getStore();
        await runEventCallbacks(socketMap.defaultEvents[eventName], data);
    };

    const runTopicEvents = async (props: IRunEventsProps) => {
        const socketMap = getStore();
        const { topic, topicId } = getTopicWithId(props);
        await runEventCallbacks(socketMap.subscriptions[topic]?.[topicId]?.[props.eventName], props.data);
    };

    const runEvents = async (props: IRunEventsProps) => {
        if (isDefaultEventName(props.eventName)) {
            await runDefaultEvents(props.eventName, props.data);
            return;
        }

        await runTopicEvents(props);
    };

    const scheduleReconnect = () => {
        setTimeout(() => {
            if (shouldReconnect()) {
                reconnect();
            }
        }, 5000);
    };

    const handleExpiredTokenClose: TCloseStatusHandler = async () => {
        const isRefreshed = await refresh();
        if (isRefreshed) {
            reconnect();
            return true;
        }

        removeAccessToken();
        return true;
    };

    const handleUnauthorizedClose: TCloseStatusHandler = async () => {
        removeAccessToken();
        return true;
    };

    const handleReconnectableClose: TCloseStatusHandler = async () => {
        scheduleReconnect();
        return true;
    };

    const handleSocketMessage = async (response: unknown) => {
        if (!response || typeof response !== "object" || !("event" in response) || typeof response.event !== "string") {
            console.error("Invalid response");
            return;
        }

        const rawTopic = "topic" in response ? response.topic : undefined;
        const topic = isSocketTopic(rawTopic) ? rawTopic : ESocketTopic.None;
        const rawTopicId = "topic_id" in response ? response.topic_id : undefined;
        const topicId = typeof rawTopicId === "string" ? rawTopicId : undefined;
        if (topic !== ESocketTopic.None && topic !== ESocketTopic.Global && topicId === undefined) {
            console.error("Invalid response");
            return;
        }

        await runEvents({
            topic,
            topicId,
            eventName: response.event,
            data: "data" in response ? response.data : undefined,
        });
    };

    const handleSocketCloseStatus = async (event: CloseEvent) => {
        switch (event.code) {
            case ESocketStatus.WS_3001_EXPIRED_TOKEN:
                return handleExpiredTokenClose();
            case ESocketStatus.WS_3000_UNAUTHORIZED:
                return handleUnauthorizedClose();
            case ESocketStatus.WS_1006_ABNORMAL_CLOSURE:
            case ESocketStatus.WS_1012_SERVICE_RESTART:
                return handleReconnectableClose();
            default:
                return false;
        }
    };

    const handleSocketClose = async (event: CloseEvent) => {
        await runStreamErrorCallbacks(event);

        if (await handleSocketCloseStatus(event)) {
            return;
        }

        await runDefaultEvents("close", event);
        closeSocket();
    };

    const handleSocketOpen = async (event: Event) => {
        await runDefaultEvents("open", event);
    };

    const handleSocketError = async (event: Event) => {
        await runStreamErrorCallbacks(event);
        await runDefaultEvents("error", event);
    };

    const connect = () => {
        const accessToken = getAccessToken();
        if (!accessToken) {
            return;
        }

        createSocket<unknown>({
            accessToken,
            onOpen: handleSocketOpen,
            onMessage: handleSocketMessage,
            onError: handleSocketError,
            onClose: handleSocketClose,
        });
    };

    return {
        connect,
    };
};
