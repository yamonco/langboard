import Auth from "@/core/security/Auth";
import SocketClient from "@/core/server/SocketClient";
import { RawData, WebSocket, WebSocketServer } from "ws";
import { IncomingMessage } from "http";
import { Utils } from "@langboard/core/utils";
import { ESocketStatus, ESocketTopic, GLOBAL_TOPIC_ID, SOCKET_MAX_TOPIC_ID_BYTES, SOCKET_MAX_TOPIC_IDS } from "@langboard/core/enums";
import EventManager from "@/core/server/EventManager";
import Hocus from "@/core/server/Hocus";
import { EDITOR_SYNC_OWNER, SOCKET_MAX_IN_FLIGHT_MB, SOCKET_MAX_IN_FLIGHT_MESSAGES, SOCKET_OWNER } from "@/Constants";

let inFlightMessageBytes = 0;
let inFlightMessageCount = 0;
let isShuttingDown = false;

const getMessageByteLength = (message: RawData): number => {
    if (Array.isArray(message)) {
        return message.reduce((total, chunk) => total + chunk.byteLength, 0);
    }
    return message.byteLength;
};

const isValidTopicId = (topicId: unknown): topicId is string =>
    typeof topicId === "string" && topicId.length > 0 && Buffer.byteLength(topicId, "utf8") <= SOCKET_MAX_TOPIC_ID_BYTES;

const isValidTopicIds = (topicIds: unknown): topicIds is string | string[] =>
    isValidTopicId(topicIds) ||
    (Array.isArray(topicIds) && topicIds.length <= SOCKET_MAX_TOPIC_IDS && topicIds.every((topicId) => isValidTopicId(topicId)));

class SocketManager {
    #server: WebSocketServer;

    constructor(server: WebSocketServer) {
        this.#server = server;
        this.#server.on("connection", async (ws, request) => await this.#handleConnection(ws, request));
    }

    async destroy() {
        isShuttingDown = true;
        this.#server.removeAllListeners("connection");
        while (inFlightMessageCount > 0) {
            await new Promise((resolve) => setTimeout(resolve, 25));
        }
        this.#server = null!;
    }

    async #handleConnection(ws: WebSocket, request: IncomingMessage) {
        ws.on("error", () => ws.terminate());

        if (!request?.url) {
            ws.close(ESocketStatus.WS_1008_POLICY_VIOLATION);
            return;
        }

        const url = new URL(!Utils.String.isValidURL(request.url) ? `http://localhost${request.url}` : request.url);

        if (url.pathname === "/editor-sync" || url.pathname === "/editor-sync/" || url.pathname.endsWith("/editor-sync")) {
            if (EDITOR_SYNC_OWNER !== "node") {
                ws.close(ESocketStatus.WS_1012_SERVICE_RESTART);
                return;
            }
            Hocus.handleConnection(ws, request);
            return;
        }

        if (SOCKET_OWNER !== "node") {
            ws.close(ESocketStatus.WS_1012_SERVICE_RESTART);
            return;
        }

        ws.pause();
        const closePausedSocket = (code: ESocketStatus) => {
            ws.resume();
            ws.close(code);
        };

        const authorizationToken = url.searchParams.get("authorization");
        if (!authorizationToken) {
            closePausedSocket(ESocketStatus.WS_3000_UNAUTHORIZED);
            return;
        }

        let user;
        try {
            user = await Auth.validateToken("socket", url.searchParams);
        } catch {
            closePausedSocket(ESocketStatus.WS_1011_INTERNAL_ERROR);
            return;
        }
        if (!user || ws.readyState !== WebSocket.OPEN) {
            closePausedSocket(ESocketStatus.WS_3000_UNAUTHORIZED);
            return;
        }

        const client = new SocketClient(ws, user, authorizationToken);

        let pingTimer: NodeJS.Timeout | null = null;
        const ping = () => {
            if (pingTimer) {
                clearTimeout(pingTimer);
                pingTimer = null;
            }

            ws.ping();

            pingTimer = setTimeout(ping, 30000);
        };

        ping();

        let inFlightMessages = 0;
        let messageQueue: Promise<void> = Promise.resolve();
        ws.on("message", (message) => {
            if (isShuttingDown) {
                ws.close(ESocketStatus.WS_1012_SERVICE_RESTART);
                return;
            }

            const messageBytes = getMessageByteLength(message);
            ++inFlightMessages;
            ++inFlightMessageCount;
            inFlightMessageBytes += messageBytes;
            if (inFlightMessages > SOCKET_MAX_IN_FLIGHT_MESSAGES || inFlightMessageBytes > SOCKET_MAX_IN_FLIGHT_MB * 1024 * 1024) {
                ws.close(ESocketStatus.WS_1013_TRY_AGAIN_LATER, "WebSocket in-flight limit exceeded");
                --inFlightMessages;
                --inFlightMessageCount;
                inFlightMessageBytes -= messageBytes;
                return;
            }

            messageQueue = messageQueue.then(async () => {
                try {
                    if (ws.readyState !== WebSocket.OPEN || Utils.Type.isNullOrUndefined(message)) {
                        return;
                    }

                    if (!message.toString()) {
                        await ws.send("");
                        return;
                    }

                    const decoder = new TextDecoder("utf-8");
                    let parsedMessage;
                    try {
                        parsedMessage = Utils.Json.Parse(decoder.decode(message as ArrayBuffer));
                    } catch (error) {
                        return;
                    }

                    if (!parsedMessage || typeof parsedMessage !== "object" || Array.isArray(parsedMessage)) {
                        return;
                    }

                    const { event, topic, topic_id, data } = parsedMessage;
                    if (typeof event !== "string" || typeof topic !== "string") {
                        return;
                    }

                    switch (event) {
                        case "subscribe":
                            if (!isValidTopicIds(topic_id)) {
                                ws.close(ESocketStatus.WS_4001_INVALID_DATA);
                                return;
                            }
                            await client.subscribe(topic, topic_id);
                            break;
                        case "unsubscribe":
                            if (!isValidTopicIds(topic_id)) {
                                ws.close(ESocketStatus.WS_4001_INVALID_DATA);
                                return;
                            }
                            await client.unsubscribe(topic, topic_id);
                            break;
                        default:
                            await EventManager.emit(topic, event, {
                                client,
                                data,
                                topicId: topic_id,
                            });
                    }
                } catch {
                    ws.close(ESocketStatus.WS_1011_INTERNAL_ERROR);
                } finally {
                    --inFlightMessages;
                    --inFlightMessageCount;
                    inFlightMessageBytes -= messageBytes;
                }
            });
        });

        ws.on("close", async () => {
            if (pingTimer) {
                clearTimeout(pingTimer);
                pingTimer = null;
            }
        });

        try {
            await client.subscribe(ESocketTopic.Global, [GLOBAL_TOPIC_ID]);
            await client.subscribe(ESocketTopic.UserPrivate, [user.uid]);
            if (ws.readyState === WebSocket.OPEN) {
                ws.resume();
            }
        } catch {
            closePausedSocket(ESocketStatus.WS_1011_INTERNAL_ERROR);
        }
    }
}

export default SocketManager;
