import { ESocketTopic } from "@langboard/core/enums";

export type TDefaultEvents = "open" | "close" | "error";
export type TEventName = TDefaultEvents | (string & {});
export type TSocketImplicitTopic = ESocketTopic.None | ESocketTopic.Global;
export type TSocketScopedTopic = Exclude<ESocketTopic, TSocketImplicitTopic>;
export type TSocketNonDefaultEventName = Exclude<TEventName, TDefaultEvents>;

export interface ISocketEvent<TResponse> {
    (data: TResponse): void;
}

export type TSocketTopicId = string;
export type TSocketEventKey = string;
export type TSocketEventCallbacks<TResponse = unknown> = ISocketEvent<TResponse>[];
export type TSocketEventKeyMap<TResponse = unknown> = Record<TSocketEventKey, TSocketEventCallbacks<TResponse>>;
export type TEventMap = Partial<Record<TEventName, TSocketEventKeyMap>>;
export type TSocketSubscriptionMap = Record<TSocketTopicId, TEventMap>;
export type TSocketSubscriptionTopicMap = Partial<Record<ESocketTopic, TSocketSubscriptionMap>>;
export type TSocketDefaultEventMap = Partial<Record<TDefaultEvents, TSocketEventKeyMap>>;
export type TSocketCallbackQueue = (() => void)[];
export type TSocketTopicCallbackQueueMap = Partial<Record<ESocketTopic, Record<TSocketTopicId, TSocketCallbackQueue>>>;
export type TSocketSubscribedTopicMap = Partial<Record<ESocketTopic, TSocketTopicId[]>>;

export interface ISocketCreateSocketProps<TResponse> {
    accessToken: string;
    onOpen: (event: Event) => Promise<void> | void;
    onMessage: (response: TResponse) => Promise<void> | void;
    onError: (event: Event) => Promise<void> | void;
    onClose: (event: CloseEvent) => Promise<void> | void;
}

interface IBaseSocketAddEventProps<TResponse> {
    eventKey: string;
    callback: ISocketEvent<TResponse>;
}

interface INoneOrGlobalTopicSocketAddEventProps<TResponse> extends IBaseSocketAddEventProps<TResponse> {
    topic: TSocketImplicitTopic;
    topicId?: never;
    event: TSocketNonDefaultEventName;
}

interface ITopicSocketAddEventProps<TResponse> extends IBaseSocketAddEventProps<TResponse> {
    topic: TSocketScopedTopic;
    topicId: string;
    event: TSocketNonDefaultEventName;
}

interface IDefaultSocketAddEventProps<TResponse> extends IBaseSocketAddEventProps<TResponse> {
    topic?: never;
    topicId?: never;
    event: TDefaultEvents;
}

export type TSocketAddEventProps<TResponse> =
    | INoneOrGlobalTopicSocketAddEventProps<TResponse>
    | ITopicSocketAddEventProps<TResponse>
    | IDefaultSocketAddEventProps<TResponse>;

interface IBaseSocketRemoveEventProps {
    eventKey: string;
    callback: ISocketEvent<unknown>;
}

interface INoneOrGlobalTopicSocketRemoveEventProps extends IBaseSocketRemoveEventProps {
    topic: TSocketImplicitTopic;
    topicId?: never;
    event: TSocketNonDefaultEventName;
}

interface ITopicSocketRemoveEventProps extends IBaseSocketRemoveEventProps {
    topic: TSocketScopedTopic;
    topicId: string;
    event: TSocketNonDefaultEventName;
}

interface IDefaultSocketRemoveEventProps extends IBaseSocketRemoveEventProps {
    topic?: never;
    topicId?: never;
    event: TDefaultEvents;
}

export type TSocketRemoveEventProps = INoneOrGlobalTopicSocketRemoveEventProps | ITopicSocketRemoveEventProps | IDefaultSocketRemoveEventProps;

interface IBaseSocketTopicNotifierProps {
    topic: ESocketTopic;
    topicId?: string;
    key: string;
    notifier: TSocketTopicNotifier;
}

interface INoneOrGlobalSocketTopicNotifierProps extends IBaseSocketTopicNotifierProps {
    topic: TSocketImplicitTopic;
    topicId?: never;
}

interface ITopicSocketTopicNotifierProps extends IBaseSocketTopicNotifierProps {
    topic: TSocketScopedTopic;
    topicId: string;
}

export type TSocketTopicNotifierProps = INoneOrGlobalSocketTopicNotifierProps | ITopicSocketTopicNotifierProps;

interface IBaseSocketTopicNotifierRemoveProps {
    topic: ESocketTopic;
    topicId?: string;
    key: string;
}

interface INoneOrGlobalSocketTopicNotifierRemoveProps extends IBaseSocketTopicNotifierRemoveProps {
    topic: TSocketImplicitTopic;
    topicId?: never;
}

interface ITopicSocketTopicNotifierRemoveProps extends IBaseSocketTopicNotifierRemoveProps {
    topic: TSocketScopedTopic;
    topicId: string;
}

export type TSocketTopicNotifierRemoveProps = INoneOrGlobalSocketTopicNotifierRemoveProps | ITopicSocketTopicNotifierRemoveProps;

export type TSocketTopicNotifier = (topicId: string, isSubscribed: bool) => void;
export type TSocketTopicNotifierKeyMap = Record<string, TSocketTopicNotifier>;
export type TSocketTopicNotifierTopicMap = Record<TSocketTopicId, TSocketTopicNotifierKeyMap>;
export type TSocketTopicNotifierMap = Partial<Record<ESocketTopic, TSocketTopicNotifierTopicMap>>;

export interface ISocketMap {
    subscriptions: TSocketSubscriptionTopicMap;
    defaultEvents: TSocketDefaultEventMap;
    sendingQueue: string[];
    sendingQueueTimeout?: NodeJS.Timeout;
    subscribedCallbackQueue: TSocketTopicCallbackQueueMap;
    unsubscribedCallbackQueue: TSocketTopicCallbackQueueMap;
    subscribedTopicNotifiers: TSocketTopicNotifierMap;
    subscribedTopics: TSocketSubscribedTopicMap;
}

export interface ISocketStore {
    getSocket: () => WebSocket | null;
    createSocket: <TResponse>(props: ISocketCreateSocketProps<TResponse>) => WebSocket;
    getStore: () => ISocketMap;
    addEvent: (props: TSocketAddEventProps<unknown>) => void;
    removeEvent: (props: TSocketRemoveEventProps) => void;
    send: (json: string) => bool;
    close: () => void;
    subscribe: (topic: TSocketScopedTopic, topicIds: string[], callback?: () => void) => void;
    unsubscribe: (topic: TSocketScopedTopic, topicIds: string[], callback?: () => void) => void;
    subscribeTopicNotifier: (props: TSocketTopicNotifierProps) => void;
    unsubscribeTopicNotifier: (props: TSocketTopicNotifierRemoveProps) => void;
    isSubscribed: (topic: TSocketScopedTopic, topicId: string) => bool;
}
