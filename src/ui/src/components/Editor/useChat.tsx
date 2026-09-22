/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import * as React from "react";
import type { ChatTransport, UIMessage, UIMessageChunk } from "ai";
import { ISocketContext } from "@/core/providers/SocketProvider";
import { useChat as useBaseChat, UseChatHelpers } from "@ai-sdk/react";
import { Utils } from "@langboard/core/utils";
import { ESocketTopic } from "@langboard/core/enums";
import { cancelEditorRun, isEditorRunCancellationPending } from "@/controllers/socket/shared/EditorAIRunCancellation";
import { EDITOR_AI_STATUS_MAX_POLLS, EDITOR_AI_STATUS_POLL_INTERVAL_MS } from "@/core/constants/InternalBotRun";

export const EDITOR_CHAT_KEY = "chat";

export interface IUseChat {
    socket: ISocketContext;
    eventKey: string;
    events: {
        abort: string;
        send: string;
        stream: string;
        status: string;
        statusResult: string;
    };
    commonEventData?: Record<string, any>;
}

export type TAIChatOption = UseChatHelpers<UIMessage> & {
    abort?: () => void;
};

type TUseBaseChat = ReturnType<typeof useBaseChat>;

interface IUseEditorChat extends TUseBaseChat {
    abort: () => void;
}

interface ISocketStreamBufferPayload {
    message?: string;
}

interface ISocketStreamEndPayload extends ISocketStreamBufferPayload {
    status?: string;
}

interface ICreateSocketMessageStreamProps extends Pick<IUseChat, "socket" | "eventKey" | "events"> {
    taskID: string;
    payload: Record<string, unknown>;
    signal?: AbortSignal;
    sendRequest?: boolean;
}

interface ILegacyMessage {
    role: UIMessage["role"];
    content: string;
}

const getMessageContent = (message: UIMessage): string => {
    const text = message.parts.reduce((currentText, part) => (part.type === "text" ? `${currentText}${part.text}` : currentText), "");
    if (text.length > 0) {
        return text;
    }

    const fallbackContent = (message as unknown as Record<string, unknown>).content;
    return Utils.Type.isString(fallbackContent) ? fallbackContent : "";
};

const toLegacyMessages = (messages: UIMessage[]): ILegacyMessage[] => {
    return messages.map((message) => ({
        role: message.role,
        content: getMessageContent(message),
    }));
};

const toSafeMessage = (value: unknown): string => (Utils.Type.isString(value) ? value : "");

export const EDITOR_AI_RUN_STORAGE_PREFIX = "langboard:editor-ai-run:";

export const getEditorRunStorageKey = (eventKey: string): string => `${EDITOR_AI_RUN_STORAGE_PREFIX}${eventKey}`;

export const readStoredEditorRun = (eventKey: string): string | null => {
    if (typeof window === "undefined") {
        return null;
    }

    try {
        return window.sessionStorage.getItem(getEditorRunStorageKey(eventKey));
    } catch {
        return null;
    }
};

export const storeEditorRun = (eventKey: string, taskID: string): void => {
    if (typeof window === "undefined") {
        return;
    }

    try {
        window.sessionStorage.setItem(getEditorRunStorageKey(eventKey), taskID);
    } catch {
        return;
    }
};

export const clearStoredEditorRun = (eventKey: string, taskID: string): void => {
    if (typeof window === "undefined") {
        return;
    }

    try {
        const key = getEditorRunStorageKey(eventKey);
        if (window.sessionStorage.getItem(key) === taskID) {
            window.sessionStorage.removeItem(key);
        }
    } catch {
        return;
    }
};

const createSocketMessageStream = ({
    socket,
    eventKey,
    events,
    taskID,
    payload,
    signal,
    sendRequest = true,
}: ICreateSocketMessageStreamProps): ReadableStream<UIMessageChunk> => {
    return new ReadableStream<UIMessageChunk>({
        start(controller) {
            const textPartID = `${taskID}:text`;
            const chatEventKey = `plate-chat-${eventKey}:${taskID}`;

            let hasTextStarted = false;
            let isClosed = false;
            let hasConnectionLoss = !sendRequest;
            let streamedText = "";
            let statusPolls = 0;
            let statusTimer: ReturnType<typeof setTimeout> | undefined;

            const statusEventKey = `plate-chat-status-${eventKey}:${taskID}`;
            const statusResultEvent = events.statusResult;

            const clearStatusTimer = () => {
                if (statusTimer !== undefined) {
                    clearTimeout(statusTimer);
                    statusTimer = undefined;
                }
            };

            const appendText = (text: string) => {
                if (!text.length || isClosed) {
                    return;
                }

                if (!hasTextStarted) {
                    controller.enqueue({
                        type: "text-start",
                        id: textPartID,
                    });
                    hasTextStarted = true;
                }

                controller.enqueue({
                    type: "text-delta",
                    id: textPartID,
                    delta: text,
                });
                streamedText += text;
            };

            const finishWithText = (text: string) => {
                if (isClosed) {
                    return;
                }

                if (text.startsWith(streamedText)) {
                    appendText(text.slice(streamedText.length));
                } else if (!streamedText.length) {
                    appendText(text);
                }

                if (hasTextStarted) {
                    controller.enqueue({
                        type: "text-end",
                        id: textPartID,
                    });
                }

                controller.enqueue({
                    type: "finish",
                    finishReason: "stop",
                });
                clearStoredEditorRun(eventKey, taskID);
                closeStream();
            };

            const emitError = (message: string, clearRun = true) => {
                if (isClosed) {
                    return;
                }

                if (hasTextStarted) {
                    controller.enqueue({
                        type: "text-end",
                        id: textPartID,
                    });
                }

                controller.enqueue({
                    type: "error",
                    errorText: message,
                });
                controller.enqueue({
                    type: "finish",
                    finishReason: "error",
                });
                if (clearRun) {
                    clearStoredEditorRun(eventKey, taskID);
                }
                closeStream();
            };

            const scheduleStatusCheck = () => {
                if (isClosed || !hasConnectionLoss || statusTimer !== undefined) {
                    return;
                }
                if (statusPolls >= EDITOR_AI_STATUS_MAX_POLLS) {
                    emitError("Editor AI stream could not be resumed", false);
                    return;
                }

                statusTimer = setTimeout(() => {
                    statusTimer = undefined;
                    requestStatus();
                }, EDITOR_AI_STATUS_POLL_INTERVAL_MS);
            };

            const requestStatus = () => {
                if (isClosed || !hasConnectionLoss) {
                    return;
                }
                if (statusPolls >= EDITOR_AI_STATUS_MAX_POLLS) {
                    emitError("Editor AI stream could not be resumed", false);
                    return;
                }

                statusPolls += 1;
                socket.send({
                    topic: ESocketTopic.None,
                    eventName: events.status,
                    data: {
                        task_id: taskID,
                        project_uid: payload.project_uid,
                        kind: "editor_chat",
                    },
                });
                scheduleStatusCheck();
            };

            const callbacks = {
                start: () => {},
                buffer: (data: ISocketStreamBufferPayload) => {
                    if (isClosed) {
                        return;
                    }

                    appendText(toSafeMessage(data?.message));
                },
                end: (data: ISocketStreamEndPayload) => {
                    if (isClosed) {
                        return;
                    }

                    if (data?.status === "failed") {
                        emitError(toSafeMessage(data?.message) || "Failed to generate response");
                        return;
                    }

                    finishWithText(toSafeMessage(data?.message));
                },
                error: () => {
                    if (isClosed) {
                        return;
                    }

                    hasConnectionLoss = true;
                    requestStatus();
                    scheduleStatusCheck();
                },
            };

            const statusCallback = (data: Record<string, unknown>) => {
                if (isClosed || data?.task_id !== taskID) {
                    return;
                }

                const status = toSafeMessage(data.status);
                if (status === "error" && data.error_code === "unavailable") {
                    scheduleStatusCheck();
                    return;
                }
                const outputText = toSafeMessage(data.output_text);
                if (status === "completed") {
                    finishWithText(outputText);
                    return;
                }
                if (["failed", "cancelled", "uncertain", "error"].includes(status)) {
                    emitError(toSafeMessage(data.error_message) || `Editor AI run ${status}`);
                    return;
                }
                scheduleStatusCheck();
            };

            const onOpen = () => {
                if (hasConnectionLoss) {
                    clearStatusTimer();
                    requestStatus();
                }
            };

            const off = () => {
                socket.streamOff({
                    topic: ESocketTopic.None,
                    event: events.stream,
                    eventKey: chatEventKey,
                    callbacks,
                });
                socket.off({
                    topic: ESocketTopic.None,
                    event: statusResultEvent,
                    eventKey: statusEventKey,
                    callback: statusCallback,
                });
                socket.off({ event: "open", eventKey: statusEventKey, callback: onOpen });
            };

            const abortHandler = () => {
                if (isClosed) {
                    return;
                }

                if (Utils.Type.isString(payload.project_uid)) {
                    cancelEditorRun(
                        {
                            socket,
                            eventKey,
                            events,
                            projectUID: payload.project_uid,
                            kind: "editor_chat",
                            onConfirmed: (confirmedTaskID) => clearStoredEditorRun(eventKey, confirmedTaskID),
                        },
                        taskID
                    );
                }
                closeStream();
            };

            const cleanup = () => {
                clearStatusTimer();
                off();
                signal?.removeEventListener("abort", abortHandler);
            };

            const closeStream = () => {
                if (isClosed) {
                    return;
                }

                isClosed = true;
                cleanup();
                controller.close();
            };

            if (signal?.aborted) {
                clearStoredEditorRun(eventKey, taskID);
                closeStream();
                return;
            }
            signal?.addEventListener("abort", abortHandler);

            socket.stream({
                topic: ESocketTopic.None,
                event: events.stream,
                eventKey: chatEventKey,
                callbacks,
            });

            socket.on({
                topic: ESocketTopic.None,
                event: statusResultEvent,
                eventKey: statusEventKey,
                callback: statusCallback,
            });
            socket.on({ event: "open", eventKey: statusEventKey, callback: onOpen });

            if (!sendRequest) {
                requestStatus();
                scheduleStatusCheck();
                return;
            }

            const sendResult = socket.send({
                topic: ESocketTopic.None,
                eventName: events.send,
                data: {
                    ...payload,
                    task_id: taskID,
                },
            });

            if (!sendResult.isConnected) {
                emitError("Socket is not connected");
                return;
            }
            storeEditorRun(eventKey, taskID);
        },
    });
};

export const useChat = (props: IUseChat): IUseEditorChat => {
    const { socket, eventKey, events, commonEventData } = props;

    const configRef = React.useRef({
        socket,
        eventKey,
        events,
        commonEventData,
    });
    configRef.current = {
        socket,
        eventKey,
        events,
        commonEventData,
    };

    const transport = React.useMemo<ChatTransport<UIMessage>>(
        () => ({
            sendMessages: async ({ chatId, messages, abortSignal, body }) => {
                const currentConfig = configRef.current;
                const taskID = Utils.String.Token.uuid();

                const payload: Record<string, unknown> = {
                    ...(body ?? {}),
                    ...(currentConfig.commonEventData ?? {}),
                    id: chatId,
                    messages: toLegacyMessages(messages),
                };

                storeEditorRun(currentConfig.eventKey, taskID);
                return createSocketMessageStream({
                    socket: currentConfig.socket,
                    eventKey: currentConfig.eventKey,
                    events: currentConfig.events,
                    taskID,
                    payload,
                    signal: abortSignal,
                });
            },
            reconnectToStream: async ({ body }) => {
                const currentConfig = configRef.current;
                const taskID = readStoredEditorRun(currentConfig.eventKey);
                if (!taskID || isEditorRunCancellationPending(currentConfig.eventKey, taskID)) {
                    return null;
                }

                return createSocketMessageStream({
                    socket: currentConfig.socket,
                    eventKey: currentConfig.eventKey,
                    events: currentConfig.events,
                    taskID,
                    payload: {
                        ...(body ?? {}),
                        ...(currentConfig.commonEventData ?? {}),
                    },
                    sendRequest: false,
                });
            },
        }),
        []
    );

    const chat = useBaseChat({
        id: `editor:${eventKey}`,
        transport,
        resume: true,
    });

    const abort = React.useCallback(() => {
        void chat.stop();
    }, [chat]);

    return {
        ...chat,
        abort,
    };
};
