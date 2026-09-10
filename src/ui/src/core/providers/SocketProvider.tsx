import { createContext, useCallback, useContext, useEffect, useMemo, useRef } from "react";
import { useAuth } from "@/core/providers/AuthProvider";
import useSocketStore, {
    ISocketCreateSocketProps,
    ISocketEvent,
    ISocketStore,
    TEventName,
    TSocketAddEventProps,
    TSocketRemoveEventProps,
    TSocketSubscriptionAddEventProps,
    TSocketSubscriptionRemoveEventProps,
} from "@/core/stores/SocketStore";
import useAuthStore from "@/core/stores/AuthStore";
import { ESocketTopic } from "@langboard/core/enums";
import { createSocketRuntime, removeStreamErrorCallback, setStreamErrorCallback } from "@/core/providers/socket/runtime";
import { createAuthorizedWebSocketUrl } from "@/core/stores/socket/transport";

interface IBaseSocketSendProps {
    topic?: ESocketTopic;
    topicId?: string;
    eventName: Exclude<TEventName, "open" | "close" | "error">;
    data: unknown;
}

interface INoneOrGlobalTopicSocketSendProps extends IBaseSocketSendProps {
    topic: ESocketTopic.None | ESocketTopic.Global;
    topicId?: never;
}

interface ITopicSocketSendProps extends IBaseSocketSendProps {
    topic: Exclude<ESocketTopic, ESocketTopic.None | ESocketTopic.Global>;
    topicId: string;
}

export type TSocketSendProps = INoneOrGlobalTopicSocketSendProps | ITopicSocketSendProps;

type TWithoutCallback<T> = T extends unknown ? Omit<T, "callback"> : never;
type TSocketStreamAddEventProps = TWithoutCallback<TSocketSubscriptionAddEventProps<unknown>>;
type TSocketStreamRemoveEventProps = TWithoutCallback<TSocketSubscriptionRemoveEventProps<unknown>>;

export interface IStreamCallbackMap<TStartResponse = unknown, TBufferResponse = unknown, TEndResponse = unknown> {
    start: ISocketEvent<TStartResponse>;
    buffer: ISocketEvent<TBufferResponse>;
    end: ISocketEvent<TEndResponse>;
    error: ISocketCreateSocketProps<unknown>["onError"];
}

export interface ISocketContext {
    isConnected: () => bool;
    reconnect: () => void;
    getAuthorizedWebSocketUrl: (path?: string) => string | null;
    on: <TResponse>(props: TSocketAddEventProps<TResponse>) => void;
    off: <TResponse>(props: TSocketRemoveEventProps<TResponse>) => void;
    send: (props: TSocketSendProps) => { isConnected: bool };
    stream: <TStartResponse = unknown, TBufferResponse = unknown, TEndResponse = unknown>(
        props: TSocketStreamAddEventProps & { callbacks: IStreamCallbackMap<TStartResponse, TBufferResponse, TEndResponse> }
    ) => void;
    streamOff: <TStartResponse = unknown, TBufferResponse = unknown, TEndResponse = unknown>(
        props: TSocketStreamRemoveEventProps & {
            callbacks: IStreamCallbackMap<TStartResponse, TBufferResponse, TEndResponse>;
        }
    ) => void;
    subscribe: ISocketStore["subscribe"];
    unsubscribe: ISocketStore["unsubscribe"];
    subscribeTopicNotifier: ISocketStore["subscribeTopicNotifier"];
    unsubscribeTopicNotifier: ISocketStore["unsubscribeTopicNotifier"];
    close: ISocketStore["close"];
    isSubscribed: ISocketStore["isSubscribed"];
}

interface ISocketProviderProps {
    children: React.ReactNode;
}

const initialContext = {
    isConnected: () => false,
    reconnect: () => {},
    getAuthorizedWebSocketUrl: () => null,
    on: () => {},
    off: () => {},
    send: () => ({ isConnected: false }),
    stream: () => {},
    streamOff: () => {},
    subscribe: () => {},
    unsubscribe: () => {},
    subscribeTopicNotifier: () => {},
    unsubscribeTopicNotifier: () => {},
    close: () => {},
    isSubscribed: () => false,
};

const SocketContext = createContext<ISocketContext>(initialContext);

const createSharedSocketHandlers = () => {
    const {
        getSocket,
        addEvent,
        removeEvent,
        send: sendSocket,
        close,
        subscribe,
        unsubscribe,
        subscribeTopicNotifier,
        unsubscribeTopicNotifier,
        isSubscribed,
    } = useSocketStore.getState();

    const isConnected = () => {
        const socket = getSocket();
        return !!socket && socket.readyState !== WebSocket.CLOSING && socket.readyState !== WebSocket.CLOSED;
    };

    const getAuthorizedWebSocketUrl: ISocketContext["getAuthorizedWebSocketUrl"] = (path) => {
        const token = useAuthStore.getState().getToken();
        return token ? createAuthorizedWebSocketUrl(token, path) : null;
    };

    const on: ISocketContext["on"] = (props) => {
        addEvent(props);
    };

    const off: ISocketContext["off"] = (props) => {
        removeEvent(props);
    };

    const stream: ISocketContext["stream"] = (props) => {
        const { callbacks } = props;
        const addStreamEvent = <TResponse,>(suffix: "start" | "buffer" | "end", callback: ISocketEvent<TResponse>) => {
            const event = `${props.event}:${suffix}`;
            if (props.topic === ESocketTopic.None || props.topic === ESocketTopic.Global) {
                on({
                    topic: props.topic,
                    event,
                    eventKey: props.eventKey,
                    callback,
                });
                return;
            }
            if (props.topicId === undefined) {
                throw new Error(`Socket topic ${props.topic} requires a topic ID`);
            }

            on({
                topic: props.topic,
                topicId: props.topicId,
                event,
                eventKey: props.eventKey,
                callback,
            });
        };

        addStreamEvent("start", callbacks.start);
        addStreamEvent("buffer", callbacks.buffer);
        addStreamEvent("end", callbacks.end);

        setStreamErrorCallback(props.topic, props.event, callbacks.error);
    };

    const streamOff: ISocketContext["streamOff"] = (props) => {
        const removeStreamEvent = <TResponse,>(suffix: "start" | "buffer" | "end", callback: ISocketEvent<TResponse>) => {
            const event = `${props.event}:${suffix}`;
            if (props.topic === ESocketTopic.None || props.topic === ESocketTopic.Global) {
                off({
                    topic: props.topic,
                    event,
                    eventKey: props.eventKey,
                    callback,
                });
                return;
            }
            if (props.topicId === undefined) {
                throw new Error(`Socket topic ${props.topic} requires a topic ID`);
            }

            off({
                topic: props.topic,
                topicId: props.topicId,
                event,
                eventKey: props.eventKey,
                callback,
            });
        };

        removeStreamEvent("start", props.callbacks.start);
        removeStreamEvent("buffer", props.callbacks.buffer);
        removeStreamEvent("end", props.callbacks.end);

        removeStreamErrorCallback(props.topic, props.event);
    };

    const send = (props: TSocketSendProps) => {
        if (!isConnected()) {
            return { isConnected: false };
        }

        const { topic, topicId, eventName, data } = props;

        return { isConnected: sendSocket(JSON.stringify({ event: eventName, topic, topic_id: topicId, data })) };
    };

    return {
        isConnected,
        on,
        off,
        getAuthorizedWebSocketUrl,
        send,
        stream,
        streamOff,
        subscribe,
        unsubscribe,
        subscribeTopicNotifier,
        unsubscribeTopicNotifier,
        close,
        isSubscribed,
    };
};

const sharedSocketHandlers = createSharedSocketHandlers();

export const SocketProvider = ({ children }: ISocketProviderProps): React.ReactNode => {
    const { currentUser } = useAuth();
    const { createSocket, getStore, close } = useSocketStore.getState();
    const currentUserRef = useRef(currentUser);
    currentUserRef.current = currentUser;
    const connectRef = useRef<() => void>(() => {});
    const reconnect = useCallback(() => {
        connectRef.current();
    }, []);

    const runtime = useMemo(
        () =>
            createSocketRuntime({
                createSocket,
                getStore,
                closeSocket: close,
                getAccessToken: () => useAuthStore.getState().getToken() ?? undefined,
                removeAccessToken: () => useAuthStore.getState().removeToken(),
                reconnect,
                shouldReconnect: () => !!currentUserRef.current,
            }),
        [createSocket, getStore, close, reconnect]
    );
    connectRef.current = runtime.connect;
    const contextValue = useMemo(
        () => ({
            ...sharedSocketHandlers,
            reconnect,
        }),
        [reconnect]
    );

    useEffect(() => {
        if (!currentUser) {
            close();
            return;
        }

        connectRef.current();
    }, [close, currentUser]);

    if (!currentUser) {
        return children;
    }

    return <SocketContext.Provider value={contextValue}>{children}</SocketContext.Provider>;
};

export const useSocket = () => {
    const context = useContext(SocketContext);
    if (!context) {
        throw new Error("useSocket must be used within a SocketProvider");
    }
    return context;
};

export const useSocketOutsideProvider = (): Omit<ISocketContext, "reconnect" | "close"> => {
    return sharedSocketHandlers;
};
