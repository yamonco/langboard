import { getBot, IBotIsAvailableOptions, IBotRunAbortableOptions, IBotRunOptions, IBotUploadOptions } from "@/core/ai/BaseBot";
import BaseStreamResponse from "@/core/ai/responses/BaseStreamResponse";
import ISocketClient from "@/core/server/ISocketClient";
import { EInternalBotType } from "@/models/InternalBot";
import { AI_TITLE_MAX_CONCURRENCY } from "@/Constants";
import { ESocketTopic, GLOBAL_TOPIC_ID } from "@langboard/core/enums";

export interface IBotAbortOptions {
    botType: EInternalBotType;
    taskID: string;
    client?: ISocketClient;
}

class BotRunner {
    static #activeTitleRequests = 0;

    public static async run({ internalBot, data }: IBotRunOptions) {
        const bot = getBot(internalBot.bot_type);
        if (!bot) {
            return null;
        }
        return await bot.run({ internalBot, data });
    }

    public static async runAbortable({
        internalBot,
        client,
        ...options
    }: IBotRunAbortableOptions & { client?: ISocketClient }): Promise<string | BaseStreamResponse | null> {
        const bot = getBot(internalBot.bot_type);
        if (!bot) {
            return null;
        }

        let isClientClosed = false;
        const unregisterCloseHandler = client?.registerCloseHandler(() => {
            isClientClosed = true;
            void bot.abort(options.taskID);
        });
        try {
            const response = await bot.runAbortable({ internalBot, ...options });
            if (isClientClosed) {
                await bot.abort(options.taskID);
            }
            if (response instanceof BaseStreamResponse) {
                if (unregisterCloseHandler) {
                    response.onFinished(unregisterCloseHandler);
                }
            } else {
                unregisterCloseHandler?.();
            }
            return response;
        } catch (error) {
            unregisterCloseHandler?.();
            throw error;
        }
    }

    public static async createTitle({ internalBot, data }: IBotRunOptions) {
        const bot = getBot(internalBot.bot_type);
        if (!bot || this.#activeTitleRequests >= AI_TITLE_MAX_CONCURRENCY) {
            return null;
        }

        this.#activeTitleRequests++;
        try {
            return await bot.createTitle({ internalBot, data });
        } finally {
            this.#activeTitleRequests--;
        }
    }

    public static async abort({ botType, taskID, client }: IBotAbortOptions): Promise<void> {
        const bot = getBot(botType);
        if (!bot) {
            return;
        }
        await bot.abort(taskID);
        client?.send({
            topic: ESocketTopic.Global,
            topic_id: GLOBAL_TOPIC_ID,
            event: "task:aborted",
            data: {
                task_id: taskID,
            },
        });
    }

    public static async isAvailable({ internalBot }: IBotIsAvailableOptions): Promise<bool> {
        const bot = getBot(internalBot.bot_type);
        if (!bot) {
            return false;
        }
        return await bot.isAvailable({ internalBot });
    }

    public static async upload({ internalBot, file }: IBotUploadOptions): Promise<string | null> {
        const bot = getBot(internalBot.bot_type);
        if (!bot) {
            return null;
        }
        return await bot.upload({ internalBot, file });
    }

    public static isAborted(botType: EInternalBotType, task_id: string): bool {
        const bot = getBot(botType);
        if (!bot) {
            return true;
        }
        return bot.isAborted(task_id);
    }

    public static createAbortedChecker(botType: EInternalBotType, task_id: string) {
        const isAborted = () => {
            const aborted = BotRunner.isAborted(botType, task_id);
            return aborted;
        };
        return isAborted;
    }
}

export default BotRunner;
