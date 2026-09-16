import { create } from "zustand";
import {
    addEvent,
    isSubscribed,
    removeEvent,
    subscribedCallback,
    subscribeTopicNotifier,
    unsubscribedCallback,
    unsubscribeTopicNotifier,
} from "@/core/stores/socket/registry";
import { getSocket, getSocketMap } from "@/core/stores/socket/state";
import {
    closeSocketConnection,
    createSocketConnection,
    sendSocketMessage,
    subscribeToTopics,
    unsubscribeFromTopics,
} from "@/core/stores/socket/transport";
import type { ISocketStore } from "@/core/stores/socket/types";

export type {
    ISocketCreateSocketProps,
    ISocketEvent,
    ISocketMap,
    ISocketStore,
    TDefaultEvents,
    TEventMap,
    TEventName,
    TSocketAddEventProps,
    TSocketImplicitTopic,
    TSocketNonDefaultEventName,
    TSocketRemoveEventProps,
    TSocketScopedTopic,
    TSocketSubscriptionMap,
    TSocketSubscriptionTopicMap,
    TSocketTopicId,
    TSocketTopicNotifier,
    TSocketTopicNotifierMap,
    TSocketTopicNotifierProps,
    TSocketTopicNotifierRemoveProps,
} from "@/core/stores/socket/types";
export { getTopicWithId } from "@/core/stores/socket/state";

const useSocketStore = create<ISocketStore>(() => {
    const getStore = () => {
        return getSocketMap();
    };

    const send: ISocketStore["send"] = (json) => {
        return sendSocketMessage(json);
    };

    const subscribe: ISocketStore["subscribe"] = (topic, topicIds, callback) => {
        subscribeToTopics(send, topic, topicIds, callback);
    };

    const unsubscribe: ISocketStore["unsubscribe"] = (topic, topicIds, callback) => {
        unsubscribeFromTopics(send, topic, topicIds, callback);
    };

    const createSocket = ((props) => {
        return createSocketConnection({
            props,
            subscribe,
            onSubscribed: subscribedCallback,
            onUnsubscribed: unsubscribedCallback,
        });
    }) as ISocketStore["createSocket"];

    const close: ISocketStore["close"] = () => {
        closeSocketConnection();
    };

    return {
        getSocket,
        createSocket,
        getStore,
        addEvent,
        removeEvent,
        send,
        close,
        subscribe,
        unsubscribe,
        subscribeTopicNotifier,
        unsubscribeTopicNotifier,
        isSubscribed,
    };
});

export default useSocketStore;
