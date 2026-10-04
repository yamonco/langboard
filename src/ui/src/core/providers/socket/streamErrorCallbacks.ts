import { ESocketTopic } from "@langboard/core/enums";
import type { ISocketCreateSocketProps } from "@/core/stores/SocketStore";

type TStreamErrorCallback = ISocketCreateSocketProps<unknown>["onError"];

const callbacksByTopic: Partial<Record<ESocketTopic, Record<string, Record<string, TStreamErrorCallback>>>> = {};

export const setStreamErrorCallback = (topic: ESocketTopic, event: string, eventKey: string, callback: TStreamErrorCallback) => {
    callbacksByTopic[topic] ??= {};
    callbacksByTopic[topic][event] ??= {};
    callbacksByTopic[topic][event][eventKey] = callback;
};

export const removeStreamErrorCallback = (topic: ESocketTopic, event: string, eventKey: string) => {
    const callbacks = callbacksByTopic[topic]?.[event];
    if (!callbacks) {
        return;
    }

    delete callbacks[eventKey];
    if (Object.keys(callbacks).length === 0) {
        delete callbacksByTopic[topic]?.[event];
    }
};

export const runStreamErrorCallbacks = async (event: Event) => {
    for (const callbacksByEvent of Object.values(callbacksByTopic)) {
        for (const callbacks of Object.values(callbacksByEvent)) {
            for (const callback of Object.values(callbacks)) {
                await callback(event);
            }
        }
    }
};
