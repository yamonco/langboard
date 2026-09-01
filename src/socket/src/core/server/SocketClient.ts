/* eslint-disable @typescript-eslint/no-explicit-any */
import { WebSocket } from "ws";
import Subscription from "@/core/server/Subscription";
import User from "@/models/User";
import ISocketClient, { TSocketSendParams } from "@/core/server/ISocketClient";
import { Utils } from "@langboard/core/utils";
import { ESocketStatus, ESocketTopic } from "@langboard/core/enums";
import Logger from "@/core/utils/Logger";
import { SOCKET_MAX_BUFFER_MB } from "@/Constants";

class SocketClient implements ISocketClient {
    #ws: WebSocket;
    #user: User;
    #eventListeners: Partial<Record<keyof WebSocket.WebSocketEventMap, ((...args: any[]) => void)[]>>;
    #closeHandlers: Set<() => void>;
    #closed: boolean;

    public get user(): User {
        return this.#user;
    }

    constructor(ws: WebSocket, user: User) {
        this.#ws = ws;
        this.#user = user;
        this.#closeHandlers = new Set();
        this.#closed = false;
        this.#eventListeners = {
            close: [() => this.onClose()],
        };

        Object.entries(this.#eventListeners).forEach(([event, listeners]) => {
            if (!listeners) {
                return;
            }

            listeners.forEach((listener) => {
                this.#ws.addEventListener(event, listener);
            });
        });
    }

    public async subscribe(topic: ESocketTopic | string, topicId: string | string[]) {
        if (this.#closed) {
            return;
        }

        await Subscription.subscribe(this, topic, topicId);
        if (this.#closed) {
            Subscription.unsubscribeAll(this);
        }
    }

    public async unsubscribe(topic: ESocketTopic | string, topicId: string | string[]) {
        await Subscription.unsubscribe(this, topic, topicId);
    }

    public send<TData = unknown>(event: TSocketSendParams<TData>): void {
        if (this.#closed) {
            return;
        }

        event.topic = Utils.String.convertSafeEnum(ESocketTopic, event.topic);

        if (this.#ws.readyState === WebSocket.CONNECTING) {
            setTimeout(() => {
                this.send(event);
            }, 1000);
            return;
        }

        if (this.#ws.readyState !== WebSocket.OPEN) {
            return;
        }
        if (this.#ws.bufferedAmount > SOCKET_MAX_BUFFER_MB * 1024 * 1024) {
            Logger.red(`Closing slow WebSocket client after exceeding ${SOCKET_MAX_BUFFER_MB} MB send buffer.\n`);
            this.#ws.close(ESocketStatus.WS_1013_TRY_AGAIN_LATER, "WebSocket send buffer limit exceeded");
            return;
        }

        this.#ws.send(
            JSON.stringify(event),
            {
                fin: true,
            },
            (error) => {
                if (error && !["EPIPE", "ECONNRESET"].includes((error as NodeJS.ErrnoException).code ?? "")) {
                    Logger.red(error, "\n");
                }
            }
        );
    }

    public sendError(errorCode: ESocketStatus | number, message: string, shouldClose: bool = false) {
        if (this.#closed || this.#ws.readyState !== WebSocket.OPEN) {
            return;
        }

        this.#ws.send(
            JSON.stringify({
                event: "error",
                error_code: errorCode,
                message,
            }),
            {
                fin: true,
            }
        );

        if (shouldClose) {
            this.#ws.close(errorCode);
        }
    }

    public stream(topic: ESocketTopic, topicId: string, baseEvent: string) {
        topic = Utils.String.convertSafeEnum(ESocketTopic, topic);

        const send = (event: "start" | "buffer" | "end", data: Record<string, unknown> = {}) => {
            this.send({
                event: `${baseEvent}:${event}`,
                topic,
                topic_id: topicId,
                data,
            });
        };

        const start = (data: Record<string, unknown> = {}) => {
            send("start", data);
        };

        const buffer = (data: Record<string, unknown> = {}) => {
            send("buffer", data);
        };

        const end = (data: Record<string, unknown> = {}) => {
            send("end", data);
        };

        return {
            start,
            buffer,
            end,
        };
    }

    public registerCloseHandler(handler: () => void): () => void {
        if (this.#closed) {
            handler();
            return () => {};
        }

        this.#closeHandlers.add(handler);
        return () => this.#closeHandlers.delete(handler);
    }

    public onClose() {
        if (this.#closed) {
            return;
        }
        this.#closed = true;

        this.#closeHandlers.forEach((handler) => {
            try {
                handler();
            } catch {
                // Continue closing remaining client resources.
            }
        });
        this.#closeHandlers.clear();

        Object.entries(this.#eventListeners).forEach(([event, listeners]) => {
            if (!listeners) {
                return;
            }

            listeners.forEach((listener) => {
                this.#ws.removeEventListener(event, listener);
            });
        });

        Subscription.unsubscribeAll(this);

        this.#eventListeners = {};
    }
}

export default SocketClient;
