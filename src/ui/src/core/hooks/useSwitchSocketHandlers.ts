import useSocketHandler from "@/core/helpers/SocketHandler";
import useSocketStreamHandler from "@/core/hooks/useSocketStreamHandler";
import { ISocketContext } from "@/core/providers/SocketProvider";
import { getTopicWithId } from "@/core/stores/SocketStore";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import { useEffect, useMemo, useState } from "react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type TSocketHandler = ReturnType<typeof useSocketHandler<any, any>> | ReturnType<typeof useSocketStreamHandler>;

export interface IUseSwitchSocketHandlersProps {
    socket: ISocketContext;
    handlers: TSocketHandler | TSocketHandler[];
    dependencies?: unknown[];
}

const useSwitchSocketHandlers = ({ socket, handlers, dependencies }: IUseSwitchSocketHandlersProps) => {
    const handlerList = useMemo(() => (Utils.Type.isArray(handlers) ? handlers : [handlers]), [handlers]);
    const [subscribedTopics, setSubscribedTopics] = useState<ESocketTopic[]>([]);

    useEffect(() => {
        const notifiers: [ESocketTopic, string, string][] = [];
        for (let i = 0; i < handlerList.length; ++i) {
            const { topic, topicId } = getTopicWithId(handlerList[i]);

            const key = Utils.String.Token.uuid();
            notifiers.push([topic, topicId, key]);
            socket.subscribeTopicNotifier({
                topic,
                topicId: topicId as never,
                key,
                notifier: (subscribedTopicId, isSubscribed) => {
                    if (subscribedTopicId !== topicId) {
                        return;
                    }

                    setSubscribedTopics((prev) => {
                        const existed = prev.includes(topic);
                        if ((isSubscribed && existed) || (!isSubscribed && !existed)) {
                            return prev;
                        }

                        const newTopics = prev.filter((targetTopic) => targetTopic !== topic);
                        if (isSubscribed) {
                            newTopics.push(topic);
                        }

                        return newTopics;
                    });
                },
            });
        }

        return () => {
            for (let i = 0; i < notifiers.length; ++i) {
                const [topic, topicId, key] = notifiers[i];
                socket.unsubscribeTopicNotifier({ topic, topicId: topicId as never, key });
            }
        };
    }, [handlerList, socket]);

    useEffect(() => {
        const offs: (() => void)[] = [];
        for (let i = 0; i < handlerList.length; ++i) {
            offs.push(handlerList[i].on());
        }

        return () => {
            for (let i = 0; i < offs.length; ++i) {
                offs[i]();
            }
        };
    }, [handlerList, ...(dependencies ?? [])]);

    return { subscribedTopics };
};

export default useSwitchSocketHandlers;
