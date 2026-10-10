/* eslint-disable @typescript-eslint/no-explicit-any */
import { refresh } from "@/core/helpers/Api";
import { getTopicWithId, ISocketCreateSocketProps, ISocketStore, TEventName } from "@/core/stores/SocketStore";
import { ESocketStatus, ESocketTopic } from "@langboard/core/enums";
import type { TSocketEventKeyMap } from "@/core/stores/socket/types";

interface IBaseRunEventsProps {
    topic?: ESocketTopic;
    topicId?: string;
    eventName: TEventName;
    data?: unknown;
}

interface INoneTopicRunEventsProps extends IBaseRunEventsProps {
    topic: ESocketTopic.None;
    topicId?: never;
    eventName: Exclude<TEventName, "open" | "close" | "error">;
}

interface IGlobalTopicRunEventsProps extends IBaseRunEventsProps {
    topic: ESocketTopic.Global;
    topicId?: never;
    eventName: Exclude<TEventName, "open" | "close" | "error">;
}

interface ITopicRunEventsProps extends IBaseRunEventsProps {
    topic: Exclude<ESocketTopic, ESocketTopic.None | ESocketTopic.Global>;
    topicId: string;
    eventName: Exclude<TEventName, "open" | "close" | "error">;
}

interface IDefaultEventsRunEventsProps extends IBaseRunEventsProps {
    topic?: never;
    topicId?: never;
    eventName: "open" | "close" | "error";
}

type TRunEventsProps = INoneTopicRunEventsProps | IGlobalTopicRunEventsProps | ITopicRunEventsProps | IDefaultEventsRunEventsProps;
type TStreamErrorCallback = ISocketCreateSocketProps<unknown>["onError"];
type TCloseStatusHandler = () => Promise<bool>;

const streamErrorCallbacks: Partial<Record<ESocketTopic, Record<string, TStreamErrorCallback>>> = {};

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
    const topics = Object.keys(streamErrorCallbacks) as ESocketTopic[];
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
                await callbacks[j](data);
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

    const runTopicEvents = async (props: Exclude<TRunEventsProps, IDefaultEventsRunEventsProps>) => {
        const socketMap = getStore();
        const { topic, topicId } = getTopicWithId(props);
        await runEventCallbacks(socketMap.subscriptions[topic]?.[topicId]?.[props.eventName], props.data);
    };

    const runEvents = async (props: TRunEventsProps) => {
        if (isDefaultEventName(props.eventName)) {
            await runDefaultEvents(props.eventName, props.data);
            return;
        }

        await runTopicEvents(props as Exclude<TRunEventsProps, IDefaultEventsRunEventsProps>);
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

    const handleSocketMessage = async (response: Record<string, any>) => {
        if (!response.event) {
            console.error("Invalid response");
            return;
        }

        await runEvents({
            topic: response.topic ?? ESocketTopic.None,
            topicId: response.topic_id,
            eventName: response.event,
            data: response.data,
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

        createSocket<Record<string, any>>({
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
