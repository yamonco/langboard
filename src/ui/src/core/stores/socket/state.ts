import { ESocketTopic, GLOBAL_TOPIC_ID, NONE_TOPIC_ID } from "@langboard/core/enums";
import type { ISocketMap } from "@/core/stores/socket/types";

const createSocketMap = (): ISocketMap => ({
    subscriptions: {},
    defaultEvents: {},
    sendingQueue: [],
    subscribedCallbackQueue: {},
    unsubscribedCallbackQueue: {},
    subscribedTopicNotifiers: {},
    subscribedTopics: {},
});

const socketMap: ISocketMap = createSocketMap();

let socket: WebSocket | null = null;

export const getSocketMap = () => {
    return socketMap;
};

export const getSocket = () => {
    return socket;
};

export const setSocket = (nextSocket: WebSocket | null) => {
    socket = nextSocket;
};

export const isSocketOpenOrConnecting = (targetSocket: WebSocket | null = socket) => {
    return !!targetSocket && (targetSocket.readyState === WebSocket.OPEN || targetSocket.readyState === WebSocket.CONNECTING);
};

export const canCloseSocket = (targetSocket: WebSocket | null = socket) => {
    return !!targetSocket && targetSocket.readyState !== WebSocket.CLOSING && targetSocket.readyState !== WebSocket.CLOSED;
};

export const resetSocketConnectionState = () => {
    socketMap.sendingQueue.splice(0);
    delete socketMap.sendingQueueTimeout;
    socketMap.subscriptions = {};
    socketMap.subscribedCallbackQueue = {};
    socketMap.unsubscribedCallbackQueue = {};
    socketMap.subscribedTopicNotifiers = {};
    socketMap.subscribedTopics = {};
};

export const isSocketTopicWithoutId = (topic: ESocketTopic) => {
    return topic === ESocketTopic.None || topic === ESocketTopic.Global;
};

export const resolveSocketTopicId = (topic: ESocketTopic, topicId?: string) => {
    switch (topic) {
        case ESocketTopic.None:
            return NONE_TOPIC_ID;
        case ESocketTopic.Global:
            return GLOBAL_TOPIC_ID;
        default:
            return topicId!;
    }
};

export const getTopicWithId = (props: { topic?: ESocketTopic; topicId?: string }) => {
    const topic = props.topic ?? ESocketTopic.None;

    return { topic, topicId: resolveSocketTopicId(topic, props.topicId) };
};
