import { ESocketTopic } from "@langboard/core/enums";
import { getSocketMap, getTopicWithId } from "@/core/stores/socket/state";
import type {
    TDefaultEvents,
    TSocketAddEventProps,
    TSocketRemoveEventProps,
    TSocketTopicNotifierProps,
    TSocketTopicNotifierRemoveProps,
    TSocketEventKeyMap,
    TSocketTopicNotifierKeyMap,
} from "@/core/stores/socket/types";

type TSocketCallbackQueueName = "subscribedCallbackQueue" | "unsubscribedCallbackQueue";

const pushUniqueValue = <T>(items: T[], value: T) => {
    if (items.includes(value)) {
        return false;
    }

    items.push(value);
    return true;
};

const removeValue = <T>(items: T[], value: T) => {
    for (let i = 0; i < items.length; ++i) {
        if (items[i] !== value) {
            continue;
        }

        items.splice(i, 1);
        --i;
    }
};

const runCallbacks = (callbacks?: (() => void)[]) => {
    if (!callbacks?.length) {
        return;
    }

    for (let i = 0; i < callbacks.length; ++i) {
        callbacks[i]();
    }
};

const isEmptyRecord = (record?: Record<string, unknown>) => {
    if (!record) {
        return true;
    }

    for (const _key in record) {
        return false;
    }

    return true;
};

const isDefaultEvent = (event: string): event is TDefaultEvents => {
    return event === "open" || event === "close" || event === "error";
};

const getDefaultEventCallbacks = (event: TDefaultEvents, eventKey: string, shouldCreate: bool) => {
    const socketMap = getSocketMap();

    if (!socketMap.defaultEvents[event]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.defaultEvents[event] = {};
    }

    if (!socketMap.defaultEvents[event][eventKey]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.defaultEvents[event][eventKey] = [];
    }

    return socketMap.defaultEvents[event][eventKey];
};

const clearDefaultEventCallbacks = (event: TDefaultEvents, eventKey: string) => {
    const socketMap = getSocketMap();

    if (!socketMap.defaultEvents[event]?.[eventKey]) {
        return;
    }

    delete socketMap.defaultEvents[event][eventKey];

    if (isEmptyRecord(socketMap.defaultEvents[event])) {
        delete socketMap.defaultEvents[event];
    }
};

const getSubscriptionEventCallbacks = (topic: ESocketTopic, topicId: string, event: string, shouldCreate: bool) => {
    const socketMap = getSocketMap();

    if (!socketMap.subscriptions[topic]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.subscriptions[topic] = {};
    }

    if (!socketMap.subscriptions[topic][topicId]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.subscriptions[topic][topicId] = {};
    }

    if (!socketMap.subscriptions[topic][topicId][event]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.subscriptions[topic][topicId][event] = {};
    }

    return socketMap.subscriptions[topic][topicId][event] as TSocketEventKeyMap;
};

const clearSubscriptionEventCallbacks = (topic: ESocketTopic, topicId: string, event: string) => {
    const socketMap = getSocketMap();
    const topicSubscriptions = socketMap.subscriptions[topic];

    if (!topicSubscriptions) {
        return;
    }

    const topicEventMap = topicSubscriptions[topicId];

    if (!topicEventMap) {
        return;
    }

    if (isEmptyRecord(topicEventMap[event])) {
        delete topicEventMap[event];
    }

    if (isEmptyRecord(topicEventMap)) {
        delete topicSubscriptions[topicId];
    }

    if (isEmptyRecord(topicSubscriptions)) {
        delete socketMap.subscriptions[topic];
    }
};

const getQueuedCallbacks = (queue: TSocketCallbackQueueName, topic: ESocketTopic, topicId: string, shouldCreate: bool) => {
    const socketMap = getSocketMap();

    if (!socketMap[queue][topic]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap[queue][topic] = {};
    }

    if (!socketMap[queue][topic][topicId]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap[queue][topic][topicId] = [];
    }

    return socketMap[queue][topic][topicId];
};

const clearQueuedCallbacks = (queue: TSocketCallbackQueueName, topic: ESocketTopic, topicId: string) => {
    const socketMap = getSocketMap();

    if (!socketMap[queue][topic]?.[topicId]) {
        return;
    }

    delete socketMap[queue][topic][topicId];

    if (isEmptyRecord(socketMap[queue][topic])) {
        delete socketMap[queue][topic];
    }
};

const addSubscribedTopicId = (topic: ESocketTopic, topicId: string) => {
    const socketMap = getSocketMap();

    if (!socketMap.subscribedTopics[topic]) {
        socketMap.subscribedTopics[topic] = [];
    }

    pushUniqueValue(socketMap.subscribedTopics[topic], topicId);
};

const removeSubscribedTopicId = (topic: ESocketTopic, topicId: string) => {
    const socketMap = getSocketMap();
    const subscribedTopicIds = socketMap.subscribedTopics[topic];

    if (!subscribedTopicIds) {
        return;
    }

    removeValue(subscribedTopicIds, topicId);

    if (!subscribedTopicIds.length) {
        delete socketMap.subscribedTopics[topic];
    }
};

const getTopicNotifierMap = (topic: ESocketTopic, topicId: string, shouldCreate: bool) => {
    const socketMap = getSocketMap();

    if (!socketMap.subscribedTopicNotifiers[topic]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.subscribedTopicNotifiers[topic] = {};
    }

    if (!socketMap.subscribedTopicNotifiers[topic][topicId]) {
        if (!shouldCreate) {
            return undefined;
        }

        socketMap.subscribedTopicNotifiers[topic][topicId] = {};
    }

    return socketMap.subscribedTopicNotifiers[topic][topicId] as TSocketTopicNotifierKeyMap;
};

const clearTopicNotifier = (topic: ESocketTopic, topicId: string, key: string) => {
    const socketMap = getSocketMap();
    const notifierTopicMap = socketMap.subscribedTopicNotifiers[topic];

    if (!notifierTopicMap?.[topicId]) {
        return;
    }

    delete notifierTopicMap[topicId][key];

    if (isEmptyRecord(notifierTopicMap[topicId])) {
        delete notifierTopicMap[topicId];
    }

    if (isEmptyRecord(notifierTopicMap)) {
        delete socketMap.subscribedTopicNotifiers[topic];
    }
};

const notifyTopicNotifiers = (topic: ESocketTopic, topicId: string, isSubscribed: bool) => {
    const socketMap = getSocketMap();
    const notifierMap = socketMap.subscribedTopicNotifiers[topic]?.[topicId];

    if (!notifierMap) {
        return;
    }

    const notifiers = Object.values(notifierMap);
    for (let i = 0; i < notifiers.length; ++i) {
        notifiers[i](topicId, isSubscribed);
    }
};

export const addEvent = (props: TSocketAddEventProps<unknown>) => {
    const { event, eventKey, callback } = props;

    if (isDefaultEvent(event)) {
        const callbacks = getDefaultEventCallbacks(event, eventKey, true)!;
        pushUniqueValue(callbacks, callback);
        return;
    }

    const { topic, topicId } = getTopicWithId(props);
    const events = getSubscriptionEventCallbacks(topic, topicId, event, true)!;

    if (!events[eventKey]) {
        events[eventKey] = [];
    }

    pushUniqueValue(events[eventKey], callback);
};

export const removeEvent = (props: TSocketRemoveEventProps) => {
    const { event, eventKey, callback } = props;

    if (isDefaultEvent(event)) {
        const callbacks = getDefaultEventCallbacks(event, eventKey, false);
        if (!callbacks) {
            return;
        }

        removeValue(callbacks, callback);
        if (!callbacks.length) {
            clearDefaultEventCallbacks(event, eventKey);
        }
        return;
    }

    const { topic, topicId } = getTopicWithId(props);
    const events = getSubscriptionEventCallbacks(topic, topicId, event, false);

    if (!events?.[eventKey]) {
        return;
    }

    removeValue(events[eventKey], callback);
    if (!events[eventKey].length) {
        delete events[eventKey];
    }

    clearSubscriptionEventCallbacks(topic, topicId, event);
};

export const queueSubscribedCallback = (
    topic: Exclude<ESocketTopic, ESocketTopic.None | ESocketTopic.Global>,
    topicIds: string[],
    callback?: () => void
) => {
    if (!callback) {
        return;
    }

    for (let i = 0; i < topicIds.length; ++i) {
        const topicId = topicIds[i];
        const callbacks = getQueuedCallbacks("subscribedCallbackQueue", topic, topicId, true)!;
        pushUniqueValue(callbacks, callback);
    }
};

export const queueUnsubscribedCallback = (
    topic: Exclude<ESocketTopic, ESocketTopic.None | ESocketTopic.Global>,
    topicIds: string[],
    callback?: () => void
) => {
    if (!callback) {
        return;
    }

    for (let i = 0; i < topicIds.length; ++i) {
        const topicId = topicIds[i];
        const callbacks = getQueuedCallbacks("unsubscribedCallbackQueue", topic, topicId, true)!;
        pushUniqueValue(callbacks, callback);
    }
};

export const subscribedCallback = (topic: ESocketTopic, topicIds: string[]) => {
    const socketMap = getSocketMap();

    if (!socketMap.subscriptions[topic]) {
        socketMap.subscriptions[topic] = {};
    }

    for (let i = 0; i < topicIds.length; ++i) {
        const topicId = topicIds[i];

        if (!socketMap.subscriptions[topic][topicId]) {
            socketMap.subscriptions[topic][topicId] = {};
        }

        addSubscribedTopicId(topic, topicId);

        const callbacks = getQueuedCallbacks("subscribedCallbackQueue", topic, topicId, false);
        runCallbacks(callbacks);
        clearQueuedCallbacks("subscribedCallbackQueue", topic, topicId);

        notifyTopicNotifiers(topic, topicId, true);
    }
};

export const unsubscribedCallback = (topic: ESocketTopic, topicIds: string[]) => {
    const socketMap = getSocketMap();

    for (let i = 0; i < topicIds.length; ++i) {
        const topicId = topicIds[i];

        removeSubscribedTopicId(topic, topicId);

        if (socketMap.subscriptions[topic]) {
            delete socketMap.subscriptions[topic][topicId];
        }

        clearQueuedCallbacks("subscribedCallbackQueue", topic, topicId);

        const callbacks = getQueuedCallbacks("unsubscribedCallbackQueue", topic, topicId, false);
        runCallbacks(callbacks);
        clearQueuedCallbacks("unsubscribedCallbackQueue", topic, topicId);

        notifyTopicNotifiers(topic, topicId, false);

        if (isEmptyRecord(socketMap.subscriptions[topic])) {
            delete socketMap.subscriptions[topic];
        }
    }
};

export const subscribeTopicNotifier = (props: TSocketTopicNotifierProps) => {
    const socketMap = getSocketMap();
    const { topic, topicId } = getTopicWithId(props);
    const { key, notifier } = props;

    const subscribedNotifier = getTopicNotifierMap(topic, topicId, true)!;

    if (subscribedNotifier[key]) {
        return;
    }

    subscribedNotifier[key] = notifier;

    if (socketMap.subscribedTopics[topic]?.includes(topicId)) {
        notifier(topicId, true);
    }
};

export const unsubscribeTopicNotifier = (props: TSocketTopicNotifierRemoveProps) => {
    const { topic, topicId } = getTopicWithId(props);
    const { key } = props;

    clearTopicNotifier(topic, topicId, key);
};

export const isSubscribed = (topic: Exclude<ESocketTopic, ESocketTopic.None | ESocketTopic.Global>, topicId: string) => {
    const socketMap = getSocketMap();
    return socketMap.subscribedTopics[topic]?.includes(topicId) ?? false;
};
