import { useSocketOutsideProvider } from "@/core/providers/SocketProvider";
import { TDefaultEvents, TEventName } from "@/core/stores/SocketStore";
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
    topic: Exclude<ESocketTopic, ESocketTopic.None>;
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
    const { topic, topicId, onProps, sendProps, eventKey } = props;
    const onCallback = onProps?.callback;
    const onResponseConverter = onProps?.responseConverter;
    const onEventName = onProps ? (onProps.params ? Utils.String.format(onProps.name, onProps.params) : onProps.name) : undefined;
    const sendEventName = sendProps ? (sendProps.params ? Utils.String.format(sendProps.name, sendProps.params) : sendProps.name) : undefined;
    const hasSendProps = !!sendProps;
    const on = () => {
        if (!onEventName) {
            return () => {};
        }

        const event = (data: TResponse | TRawResponse) => {
            let newData;
            if (onResponseConverter) {
                newData = onResponseConverter(data as TRawResponse);
            } else {
                newData = data as unknown as TResponse;
            }

            onCallback?.(newData);
        };

        socket.on<TResponse>({
            topic: topic as never,
            topicId,
            event: onEventName,
            eventKey,
            callback: event,
        });

        return () => {
            socket.off({
                topic: topic as never,
                topicId,
                event: onEventName,
                eventKey,
                callback: event as unknown as (data: unknown) => void,
            });
        };
    };

    const send: (
        data: TRequest
    ) => TUseSocketHandlerProps<TResponse, TRawResponse>["sendProps"] extends undefined ? undefined : ReturnType<typeof socket.send> = (
        data: TRequest
    ) => {
        if (!hasSendProps || !sendEventName) {
            return undefined as unknown as TUseSocketHandlerProps<TResponse, TRawResponse>["sendProps"] extends undefined
                ? undefined
                : ReturnType<typeof socket.send>;
        }

        return socket.send({
            topic: topic as never,
            topicId,
            eventName: sendEventName,
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
