import assert from "node:assert/strict";
import { test } from "node:test";
import { ESocketTopic, SOCKET_MAX_TOPIC_IDS } from "@langboard/core/enums";
import { getSocketMap, resetSocketConnectionState, setSocket } from "./state";
import { subscribedCallback, unsubscribedCallback } from "./registry";
import { createSocketConnection, subscribeToTopics, unsubscribeFromTopics } from "./transport";

test("subscription frames respect the shared limit, acknowledgements, and reconnect restoration", async () => {
    const OriginalWebSocket = globalThis.WebSocket;
    class TestSocket {
        static OPEN = 1;
        static CONNECTING = 0;
        readyState = 1;
        onopen?: (event: Event) => Promise<void>;
        send() {}
    }
    globalThis.WebSocket = TestSocket as unknown as typeof WebSocket;
    try {
        for (const count of [0, SOCKET_MAX_TOPIC_IDS, SOCKET_MAX_TOPIC_IDS + 1, 92, 129]) {
            resetSocketConnectionState();
            setSocket(new TestSocket() as unknown as WebSocket);
            const ids = Array.from({ length: count }, (_, index) => `board-${index}`);
            const frames: { event: string; topic: string; topic_id: string[] }[] = [];
            const send = (frame: string) => {
                frames.push(JSON.parse(frame));
                return true;
            };
            let subscribed = 0;
            subscribeToTopics(send, ESocketTopic.Dashboard, ids, () => ++subscribed);
            assert.equal(frames.length, Math.max(1, Math.ceil(count / SOCKET_MAX_TOPIC_IDS)));
            assert.deepEqual(
                frames.flatMap((frame) => frame.topic_id),
                ids
            );
            for (const frame of frames) {
                assert.equal(frame.event, "subscribe");
                assert.equal(frame.topic, ESocketTopic.Dashboard);
                assert.ok(frame.topic_id.length <= SOCKET_MAX_TOPIC_IDS);
                subscribedCallback(ESocketTopic.Dashboard, frame.topic_id);
            }
            assert.equal(subscribed, count);
            assert.deepEqual(getSocketMap().subscribedTopics[ESocketTopic.Dashboard] ?? [], ids);

            frames.length = 0;
            setSocket(null);
            const connection = createSocketConnection({
                props: {
                    accessToken: "test-token",
                    userUID: "test-user",
                    onOpen: async () => {},
                    onMessage: async () => {},
                    onError: async () => {},
                    onClose: async () => {},
                },
                subscribe: (topic, topicIds) => subscribeToTopics(send, topic, topicIds),
                onSubscribed: subscribedCallback,
                onUnsubscribed: unsubscribedCallback,
            });
            await (connection as unknown as TestSocket).onopen!(new Event("open"));
            assert.deepEqual(
                frames.flatMap((frame) => frame.topic_id),
                ids
            );
            assert.ok(frames.every((frame) => frame.topic_id.length <= SOCKET_MAX_TOPIC_IDS));

            frames.length = 0;
            let unsubscribed = 0;
            unsubscribeFromTopics(send, ESocketTopic.Dashboard, ids, () => ++unsubscribed);
            assert.deepEqual(
                frames.flatMap((frame) => frame.topic_id),
                ids
            );
            for (const frame of frames) {
                assert.equal(frame.event, "unsubscribe");
                assert.ok(frame.topic_id.length <= SOCKET_MAX_TOPIC_IDS);
                unsubscribedCallback(ESocketTopic.Dashboard, frame.topic_id);
            }
            assert.equal(unsubscribed, count);
            assert.equal(getSocketMap().restorableTopics[ESocketTopic.Dashboard], undefined);
            assert.equal(getSocketMap().subscribedTopics[ESocketTopic.Dashboard], undefined);
        }
    } finally {
        setSocket(null);
        resetSocketConnectionState();
        globalThis.WebSocket = OriginalWebSocket;
    }
});
