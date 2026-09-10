import { useSocketOutsideProvider } from "@/core/providers/SocketProvider";
import { TDefaultEvents, TEventName, TSocketScopedTopic } from "@/core/stores/SocketStore";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";

export interface IBaseUseSocketHandlersProps<TResponse> {
    callback?: (data: TResponse) => void;
}

interface IBaseUseSocketHandlerProps<TResponse, TRawResponse, TEvent> {
    topic?: ESocketTopic;
    topicId?: string;
    eventKey: string;
    onProps?: {
        name: TEvent;
        params?: Record<string, string>;
        callback?: IBaseUseSocketHandlersProps<TResponse>["callback"];
        responseConverter?: (data: TRawResponse) => TResponse;
    };
    sendProps?: {
        name: TEvent;
        params?: Record<string, string>;
    };
}

interface INoneTopicUseSocketHandlerProps<TResponse, TRawResponse = TResponse> extends IBaseUseSocketHandlerProps<
    TResponse,
    TRawResponse,
    Exclude<TEventName, TDefaultEvents>
> {
    topic: ESocketTopic.None;
    topicId?: never;
    sendProps?: {
        name: Exclude<TEventName, TDefaultEvents>;
        params?: Record<string, string>;
    };
}

interface IGlobalTopicUseSocketHandlerProps<TResponse, TRawResponse = TResponse> extends IBaseUseSocketHandlerProps<
    TResponse,
    TRawResponse,
    Exclude<TEventName, TDefaultEvents>
> {
    topic: ESocketTopic.Global;
    topicId?: never;
}

interface ITopicUseSocketHandlerProps<TResponse, TRawResponse = TResponse> extends IBaseUseSocketHandlerProps<
    TResponse,
    TRawResponse,
    Exclude<TEventName, TDefaultEvents>
> {
    topic: TSocketScopedTopic;
    topicId: string;
}

interface IDefaultEventsUseSocketHandlerProps<TResponse, TRawResponse = TResponse> extends IBaseUseSocketHandlerProps<
    TResponse,
    TRawResponse,
    TDefaultEvents
> {
    topic?: never;
    topicId?: never;
    onProps?: {
        name: TDefaultEvents;
        params?: never;
        callback?: IBaseUseSocketHandlersProps<TResponse>["callback"];
        responseConverter?: never;
    };
    sendProps?: never;
}

export type TUseSocketHandlerProps<TResponse, TRawResponse = TResponse> =
    | INoneTopicUseSocketHandlerProps<TResponse, TRawResponse>
    | IGlobalTopicUseSocketHandlerProps<TResponse, TRawResponse>
    | ITopicUseSocketHandlerProps<TResponse, TRawResponse>
    | IDefaultEventsUseSocketHandlerProps<TResponse, TRawResponse>;

const useSocketHandler = <TResponse, TRawResponse = TResponse, TRequest = unknown>(props: TUseSocketHandlerProps<TResponse, TRawResponse>) => {
    const socket = useSocketOutsideProvider();
    const { topic, topicId, onProps, eventKey } = props;
    const onCallback = onProps?.callback;
    const onResponseConverter = onProps?.responseConverter;

    const addEvent = <TEventResponse>(callback: (data: TEventResponse) => void) => {
        if (!props.onProps) {
            return;
        }
        if (props.topic === undefined) {
            socket.on({
                event: props.onProps.name,
                eventKey,
                callback,
            });
            return;
        }

        const event = props.onProps.params ? Utils.String.format(props.onProps.name, props.onProps.params) : props.onProps.name;
        if (props.topic === ESocketTopic.None || props.topic === ESocketTopic.Global) {
            socket.on({
                topic: props.topic,
                event,
                eventKey,
                callback,
            });
            return;
        }

        socket.on({
            topic: props.topic,
            topicId: props.topicId,
            event,
            eventKey,
            callback,
        });
    };

    const removeEvent = <TEventResponse>(callback: (data: TEventResponse) => void) => {
        if (!props.onProps) {
            return;
        }
        if (props.topic === undefined) {
            socket.off({
                event: props.onProps.name,
                eventKey,
                callback,
            });
            return;
        }

        const event = props.onProps.params ? Utils.String.format(props.onProps.name, props.onProps.params) : props.onProps.name;
        if (props.topic === ESocketTopic.None || props.topic === ESocketTopic.Global) {
            socket.off({
                topic: props.topic,
                event,
                eventKey,
                callback,
            });
            return;
        }

        socket.off({
            topic: props.topic,
            topicId: props.topicId,
            event,
            eventKey,
            callback,
        });
    };

    const on = () => {
        if (!onProps) {
            return () => {};
        }

        if (onResponseConverter) {
            const event = (data: TRawResponse) => {
                const response = onResponseConverter(data);
                onCallback?.(response);
            };

            addEvent(event);

            return () => {
                removeEvent(event);
            };
        }

        const event = (data: TResponse) => {
            onCallback?.(data);
        };

        addEvent(event);

        return () => {
            removeEvent(event);
        };
    };

    const send = (data: TRequest): ReturnType<typeof socket.send> | undefined => {
        if (!props.sendProps || props.topic === undefined) {
            return undefined;
        }

        const eventName = props.sendProps.params ? Utils.String.format(props.sendProps.name, props.sendProps.params) : props.sendProps.name;
        if (props.topic === ESocketTopic.None || props.topic === ESocketTopic.Global) {
            return socket.send({
                topic: props.topic,
                eventName,
                data,
            });
        }

        return socket.send({
            topic: props.topic,
            topicId: props.topicId,
            eventName,
            data,
        });
    };

    return {
        topic,
        topicId,
        eventKey,
        send,
        on,
    };
};

export default useSocketHandler;
