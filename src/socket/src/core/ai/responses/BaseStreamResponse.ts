/* eslint-disable @typescript-eslint/no-explicit-any */
import { AI_REQUEST_TIMEOUT, AI_REQUEST_TRIALS, AI_STREAM_MAX_BUFFER_MB } from "@/Constants";
import { api } from "@/core/helpers/Api";
import Logger from "@/core/utils/Logger";
import { Utils } from "@langboard/core/utils";
import { AxiosResponse } from "axios";
import { Readable } from "stream";

export interface IStreamRespuestParams {
    url: string;
    headers?: Record<string, any>;
    body: Record<string, any>;
    signal?: AbortSignal;
    onEnd?: () => void;
    settings?: Record<string, any>;
}

export interface IStreamResponseCallbackMap {
    onMessage?: (message: string) => void | Promise<void>;
    onInterrupt?: (interrupt: Record<string, any>) => void | Promise<void>;
    onEnd?: () => void | Promise<void>;
    onError?: (error: Error) => void | Promise<void>;
}

abstract class BaseStreamResponse {
    protected registeredCallbacks: IStreamResponseCallbackMap;
    protected finishedCallbacks: Set<() => void>;
    protected retried: number;

    constructor(protected params: IStreamRespuestParams) {
        this.registeredCallbacks = {};
        this.finishedCallbacks = new Set();
        this.retried = 0;
    }

    public onMessage(callback: (message: string) => void | Promise<void>): this {
        this.registeredCallbacks.onMessage = callback;
        return this;
    }

    public onInterrupt(callback: (interrupt: Record<string, any>) => void | Promise<void>): this {
        this.registeredCallbacks.onInterrupt = callback;
        return this;
    }

    public onEnd(callback: () => void | Promise<void>): this {
        this.registeredCallbacks.onEnd = callback;
        return this;
    }

    public onError(callback: (error: Error) => void | Promise<void>): this {
        this.registeredCallbacks.onError = callback;
        return this;
    }

    public addCallbacks(callbacks: IStreamResponseCallbackMap): this {
        this.registeredCallbacks = callbacks;
        return this;
    }

    public onFinished(callback: () => void): this {
        this.finishedCallbacks.add(callback);
        return this;
    }

    public async stream(): Promise<void> {
        const { signal, onEnd, settings } = this.params;
        const { onMessage, onInterrupt, onEnd: onStreamEnd, onError } = this.registeredCallbacks;
        let isTaskFinished = false;
        const finishTask = () => {
            if (isTaskFinished) {
                return;
            }

            isTaskFinished = true;
            this.finishedCallbacks.forEach((callback) => {
                try {
                    callback();
                } catch {
                    // Continue finalizing remaining stream resources.
                }
            });
            this.finishedCallbacks.clear();
            onEnd?.();
        };

        if (signal?.aborted) {
            finishTask();
            return;
        }

        const result = await this.#createApi();
        if (!result || signal?.aborted) {
            result?.data.destroy();
            try {
                if (!result && !signal?.aborted) {
                    await onError?.(new Error("Bot stream request failed"));
                }
            } finally {
                finishTask();
            }
            return;
        }

        let abortEvent: (() => void) | undefined;
        const bufferedChunks: string[] = [];
        let bufferedBytes = 0;
        const textDecoder = new TextDecoder();

        const bufferChunk = (chunk: string) => {
            bufferedBytes += Buffer.byteLength(chunk, "utf-8");
            if (bufferedBytes > AI_STREAM_MAX_BUFFER_MB * 1024 * 1024) {
                throw new Error(`Bot stream buffer exceeded ${AI_STREAM_MAX_BUFFER_MB} MB`);
            }
            bufferedChunks.push(chunk);
        };

        const clearBuffer = () => {
            bufferedChunks.splice(0);
            bufferedBytes = 0;
        };

        const processJsonChunk = async (jsonChunk: Record<string, any>): Promise<bool> => {
            const parsedMessage = this.parseResponseChunk(jsonChunk, settings);
            if (Utils.Type.isUndefined(parsedMessage)) {
                return false;
            }
            if (Utils.Type.isString(parsedMessage)) {
                await onMessage?.(parsedMessage);
                return false;
            }
            if (!Utils.Type.isObject(parsedMessage)) {
                return false;
            }
            if (parsedMessage.error) {
                throw new Error(`Bot stream error: ${parsedMessage.error}`);
            }
            if (parsedMessage.interrupt) {
                await onInterrupt?.(parsedMessage.interrupt);
            }
            return parsedMessage.end === true;
        };

        try {
            if (signal) {
                abortEvent = () => {
                    result.data.destroy();
                };
                signal.addEventListener("abort", abortEvent, { once: true });
            }

            let streamEnded = false;
            for await (const rawChunk of result.data) {
                if (signal?.aborted) {
                    break;
                }
                const chunkString = textDecoder.decode(rawChunk, { stream: true });
                if (!chunkString.trim()) {
                    continue;
                }

                const splitChunks = chunkString.split("\n\n");
                for (let i = 0; i < splitChunks.length; ++i) {
                    const chunk = splitChunks[i];
                    if (!chunk) {
                        continue;
                    }
                    if (!chunk.endsWith("}")) {
                        bufferChunk(chunk);
                        continue;
                    }

                    let jsonChunk: Record<string, any>;
                    try {
                        jsonChunk = Utils.Json.Parse(`${bufferedChunks.join("")}${chunk}`);
                    } catch {
                        bufferChunk(chunk);
                        continue;
                    }

                    clearBuffer();
                    if (await processJsonChunk(jsonChunk)) {
                        streamEnded = true;
                        break;
                    }
                }
                if (streamEnded) {
                    break;
                }
            }

            if (!signal?.aborted && bufferedChunks.length) {
                let finalChunk: Record<string, any> | undefined;
                try {
                    finalChunk = Utils.Json.Parse(bufferedChunks.join(""));
                } catch {
                    // Ignore an incomplete final stream chunk.
                }
                if (finalChunk) {
                    await processJsonChunk(finalChunk);
                }
            }
            await onStreamEnd?.();
        } catch (error) {
            Logger.error(error, "\n");
            if (signal?.aborted) {
                await onStreamEnd?.();
            } else {
                await onError?.(Utils.Type.isError(error) ? error : new Error("An unknown error occurred while processing the bot stream response."));
            }
        } finally {
            if (abortEvent) {
                signal?.removeEventListener("abort", abortEvent);
            }
            if (!result.data.destroyed) {
                result.data.destroy();
            }
            clearBuffer();
            finishTask();
        }
    }

    public abstract parseResponseChunk(
        chunk: any,
        settings?: Record<string, any>
    ): string | { end?: true; error?: any; interrupt?: Record<string, any> } | undefined;

    async #createApi(): Promise<AxiosResponse<Readable, any> | null> {
        const { url, headers, body, signal } = this.params;

        let result: AxiosResponse<Readable, any> | null = null;
        try {
            result = await api.post<Readable>(url, body, {
                headers,
                responseType: "stream",
                timeout: AI_REQUEST_TIMEOUT * 1000,
                signal,
            });
        } catch (error) {
            result = null;
            if (signal?.aborted) {
                return null;
            }
            if (this.retried < AI_REQUEST_TRIALS) {
                ++this.retried;
                return this.#createApi();
            }

            Logger.error(error, "\n");
        }

        return result;
    }
}

export default BaseStreamResponse;
