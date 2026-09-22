/* eslint-disable @/max-len */
"use client";

import type { TElement } from "platejs";
import { CopilotPlugin } from "@platejs/ai/react";
import { serializeMd, stripMarkdown } from "@platejs/markdown";
import { Utils } from "@langboard/core/utils";
import { EHttpStatus, ESocketTopic } from "@langboard/core/enums";
import { GhostText } from "@/components/plate-ui/ghost-text";
import { clearStoredEditorRun, IUseChat, storeEditorRun } from "@/components/Editor/useChat";
import { MarkdownKit } from "@/components/Editor/plugins/markdown-kit";
import { cancelEditorRun } from "@/controllers/socket/shared/EditorAIRunCancellation";
import { EDITOR_AI_STATUS_MAX_POLLS, EDITOR_AI_STATUS_POLL_INTERVAL_MS } from "@/core/constants/InternalBotRun";

export interface ICreateCopilotKit extends Omit<IUseChat, "events"> {
    events: {
        abort: string;
        send: string;
        receive: string;
        status: string;
        statusResult: string;
    };
}

export const createCopilotKit = ({ socket, eventKey, events, commonEventData }: ICreateCopilotKit) => {
    return [
        ...MarkdownKit,
        CopilotPlugin.configure(({ api }) => ({
            options: {
                completeOptions: {
                    fetch: async (_, init) => {
                        const badResponse = new Response(null, {
                            status: EHttpStatus.HTTP_400_BAD_REQUEST,
                        });

                        if (!Utils.Type.isString(init?.body) || init.signal?.aborted) {
                            return badResponse;
                        }

                        const body = JSON.parse(init.body);
                        const key = Utils.String.Token.uuid();
                        const receiveEventWithKey = `${events.receive}:${key}`;
                        const copilotEventKey = `plate-copilot-${eventKey}-${key}`;

                        const waitResponse = new Promise((resolve) => {
                            let isSettled = false;
                            let hasSentRequest = false;
                            let hasConnectionLoss = false;
                            let statusPolls = 0;
                            let statusTimer: ReturnType<typeof setTimeout> | undefined;
                            const statusEventKey = `${copilotEventKey}:status`;

                            const clearStatusTimer = () => {
                                if (statusTimer !== undefined) {
                                    clearTimeout(statusTimer);
                                    statusTimer = undefined;
                                }
                            };

                            const cleanup = () => {
                                clearStatusTimer();
                                if (init.signal) {
                                    init.signal.onabort = null;
                                }
                                socket.off({
                                    topic: ESocketTopic.None,
                                    event: receiveEventWithKey,
                                    eventKey: copilotEventKey,
                                    callback: receive,
                                });
                                socket.off({
                                    topic: ESocketTopic.None,
                                    event: events.statusResult,
                                    eventKey: statusEventKey,
                                    callback: statusCallback,
                                });
                                socket.off({ event: "open", eventKey: statusEventKey, callback: onOpen });
                                socket.off({ event: "close", eventKey: statusEventKey, callback: onClose });
                            };

                            const finish = (text: string, clearRun = true) => {
                                if (isSettled) {
                                    return;
                                }

                                isSettled = true;
                                cleanup();
                                if (clearRun) {
                                    clearStoredEditorRun(eventKey, key);
                                }
                                resolve({ text });
                            };

                            const scheduleStatusCheck = () => {
                                if (isSettled || !hasConnectionLoss || statusTimer !== undefined) {
                                    return;
                                }
                                if (statusPolls >= EDITOR_AI_STATUS_MAX_POLLS) {
                                    finish("0", false);
                                    return;
                                }

                                statusTimer = setTimeout(() => {
                                    statusTimer = undefined;
                                    requestStatus();
                                }, EDITOR_AI_STATUS_POLL_INTERVAL_MS);
                            };

                            const requestStatus = () => {
                                if (isSettled || !hasConnectionLoss) {
                                    return;
                                }
                                if (statusPolls >= EDITOR_AI_STATUS_MAX_POLLS) {
                                    finish("0", false);
                                    return;
                                }

                                statusPolls += 1;
                                socket.send({
                                    topic: ESocketTopic.None,
                                    eventName: events.status,
                                    data: {
                                        task_id: key,
                                        project_uid: commonEventData?.project_uid,
                                        kind: "editor_copilot",
                                    },
                                });
                                scheduleStatusCheck();
                            };

                            const receive = (data: { text: string }) => {
                                if (init.signal) {
                                    init.signal.onabort = null;
                                }
                                finish(Utils.Type.isString(data?.text) ? data.text : "0");
                            };

                            const statusCallback = (data: Record<string, unknown>) => {
                                if (isSettled || data?.task_id !== key) {
                                    return;
                                }

                                const status = Utils.Type.isString(data.status) ? data.status : "";
                                if (status === "error" && data.error_code === "unavailable") {
                                    scheduleStatusCheck();
                                    return;
                                }
                                if (status === "completed") {
                                    finish(Utils.Type.isString(data.output_text) && data.output_text.length ? data.output_text : "0");
                                    return;
                                }
                                if (["failed", "cancelled", "uncertain", "error"].includes(status)) {
                                    finish("0");
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

                            const onClose = () => {
                                if (hasSentRequest && !isSettled) {
                                    hasConnectionLoss = true;
                                    scheduleStatusCheck();
                                }
                            };

                            if (init.signal) {
                                init.signal.onabort = () => {
                                    if (Utils.Type.isString(commonEventData?.project_uid)) {
                                        cancelEditorRun(
                                            {
                                                socket,
                                                eventKey,
                                                events,
                                                projectUID: commonEventData.project_uid,
                                                kind: "editor_copilot",
                                                onConfirmed: (taskID) => clearStoredEditorRun(eventKey, taskID),
                                            },
                                            key
                                        );
                                    }
                                    finish("0", false);
                                };
                            }

                            if (!init.signal?.aborted) {
                                socket.on({
                                    topic: ESocketTopic.None,
                                    eventKey: copilotEventKey,
                                    event: receiveEventWithKey,
                                    callback: receive,
                                });
                                socket.on({
                                    topic: ESocketTopic.None,
                                    eventKey: statusEventKey,
                                    event: events.statusResult,
                                    callback: statusCallback,
                                });
                                socket.on({ event: "open", eventKey: statusEventKey, callback: onOpen });
                                socket.on({ event: "close", eventKey: statusEventKey, callback: onClose });
                                const sendResult = socket.send({
                                    topic: ESocketTopic.None,
                                    eventName: events.send,
                                    data: {
                                        ...body,
                                        ...(commonEventData ?? {}),
                                        task_id: key,
                                    },
                                });
                                if (!sendResult.isConnected) {
                                    finish("0");
                                } else {
                                    hasSentRequest = true;
                                    storeEditorRun(eventKey, key);
                                }
                            }
                        });

                        const result = await waitResponse;
                        return new Response(JSON.stringify(result), {
                            headers: {
                                "Content-Type": "application/json",
                            },
                        });
                    },
                    body: {
                        system: `You are an advanced AI writing assistant, similar to VSCode Copilot but for general text. Your task is to predict and generate the next part of the text based on the given context.

  Rules:
  - Continue the text naturally up to the next punctuation mark (., ,, ;, :, ?, or !).
  - Maintain style and tone. Don't repeat given text.
  - For unclear context, provide the most likely continuation.
  - Handle code snippets, lists, or structured text if needed.
  - Don't include """ in your response.
  - CRITICAL: Always end with a punctuation mark.
  - CRITICAL: Avoid starting a new block. Do not use block formatting like >, #, 1., 2., -, etc. The suggestion should continue in the same block as the context.
  - If no context is provided or you can't generate a continuation, return "0" without explanation.`,
                    },
                    onError: () => {
                        return;
                    },
                    onFinish: (_, completion) => {
                        if (completion === "0") return;

                        api.copilot.setBlockSuggestion({
                            text: stripMarkdown(completion),
                        });
                    },
                },
                debounceDelay: 300,
                renderGhostText: GhostText,
                getPrompt: ({ editor }) => {
                    const contextEntry = editor.api.block({ highest: true });

                    if (!contextEntry) return "";

                    const prompt = serializeMd(editor, {
                        value: [contextEntry[0] as TElement],
                    });

                    return `Continue the text up to the next punctuation mark:
  """
  ${prompt}
  """`;
                },
            },
            shortcuts: {
                accept: {
                    keys: "tab",
                },
                acceptNextWord: {
                    keys: "mod+right",
                },
                reject: {
                    keys: "escape",
                },
                triggerSuggestion: {
                    keys: "ctrl+space",
                },
            },
        })),
    ];
};
