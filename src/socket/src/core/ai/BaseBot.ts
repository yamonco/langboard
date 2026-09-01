/* eslint-disable @typescript-eslint/no-explicit-any */
import { IBotRequestModel } from "@/core/ai/types";
import { Utils } from "@langboard/core/utils";
import InternalBot, { EInternalBotType } from "@/models/InternalBot";
import formidable from "formidable";
import { createRequest } from "@/core/ai/requests/utils";
import { IProjectAssignedInternalBotSettings } from "@/models/ProjectAssignedInternalBot";
import BaseStreamResponse from "@/core/ai/responses/BaseStreamResponse";

interface IBaseBotOptions {
    internalBot: InternalBot;
    internalBotSettings?: IProjectAssignedInternalBotSettings;
}

const ABORT_RACE_WINDOW_MS = 5000;
const MAX_PENDING_ABORTS = 1024;

export interface IBotRunOptions extends IBaseBotOptions {
    data: Record<string, any>;
}

export interface IBotRunAbortableOptions extends IBaseBotOptions {
    taskID: string;
    data: Record<string, any>;
}

export interface IBotIsAvailableOptions extends IBaseBotOptions {}

export interface IBotUploadOptions extends IBaseBotOptions {
    file: formidable.File;
}

export interface IBotRequestOptions {
    requestModel: IBotRequestModel;
    useStream?: bool;
}

abstract class BaseBot {
    public static get BOT_TYPE(): EInternalBotType {
        return null!;
    }
    #abortableTasks: Map<string, AbortController>;
    #pendingAborts: Map<string, NodeJS.Timeout>;

    constructor() {
        this.#abortableTasks = new Map();
        this.#pendingAborts = new Map();
    }

    public abstract run(options: IBotRunOptions): Promise<string | BaseStreamResponse | null>;
    public abstract runAbortable(options: IBotRunAbortableOptions): Promise<string | BaseStreamResponse | null>;
    public abstract createTitle(options: IBotRunOptions): Promise<string>;
    public abstract isAvailable(options: IBotIsAvailableOptions): Promise<bool>;
    public abstract upload(options: IBotUploadOptions): Promise<string | null>;

    public async abort(taskID: string): Promise<void> {
        this.#rememberPendingAbort(taskID);

        const task = this.#abortableTasks.get(taskID);
        if (!task) {
            return;
        }

        task.abort();

        this.#abortableTasks.delete(taskID);
    }

    public isAborted(taskID: string): bool {
        const task = this.#abortableTasks.get(taskID);
        if (!task) {
            return true;
        }

        return task.signal.aborted;
    }

    protected async canRequest({ internalBot, internalBotSettings }: IBaseBotOptions): Promise<bool> {
        const request = createRequest(internalBot, internalBotSettings);
        if (!request) {
            return false;
        }

        return await request.isAvailable();
    }

    protected request<TOptions extends IBaseBotOptions & IBotRequestOptions>({
        internalBot,
        internalBotSettings,
        requestModel,
        useStream = false,
    }: TOptions): Promise<TOptions["useStream"] extends true ? BaseStreamResponse | null : string | null> {
        const request = createRequest(internalBot, internalBotSettings);
        if (!request) {
            return Promise.resolve(null);
        }

        return request.execute({
            requestModel,
            useStream,
        }) as any;
    }

    protected async requestAbortable<TOptions extends IBaseBotOptions & IBotRequestOptions & { taskID: string }>({
        internalBot,
        internalBotSettings,
        taskID,
        requestModel,
        useStream = false,
    }: TOptions): Promise<TOptions["useStream"] extends true ? BaseStreamResponse | null : string | null> {
        if (this.#pendingAborts.has(taskID)) {
            return null;
        }

        const request = createRequest(internalBot, internalBotSettings);
        if (!request) {
            return Promise.resolve(null);
        }

        const abortController = new AbortController();
        const finishTask = () => {
            if (this.#abortableTasks.get(taskID) === abortController) {
                this.#abortableTasks.delete(taskID);
            }
            abortController.signal.removeEventListener("abort", onAbort);
        };
        const onAbort = () => finishTask();
        abortController.signal.addEventListener("abort", onAbort);

        this.#abortableTasks.get(taskID)?.abort();
        this.#abortableTasks.set(taskID, abortController);

        try {
            const response = await request.execute({
                requestModel,
                task: [abortController, finishTask],
                useStream,
            });
            if (!response) {
                finishTask();
            }
            return response as any;
        } catch (error) {
            finishTask();
            throw error;
        }
    }

    protected async uploadFile({ internalBot, internalBotSettings, file }: IBaseBotOptions & { file: formidable.File }): Promise<string | null> {
        const request = createRequest(internalBot, internalBotSettings);
        if (!request) {
            return null;
        }

        return await request.upload(file);
    }

    #rememberPendingAbort(taskID: string): void {
        const existingTimeout = this.#pendingAborts.get(taskID);
        if (existingTimeout) {
            clearTimeout(existingTimeout);
        } else if (this.#pendingAborts.size >= MAX_PENDING_ABORTS) {
            const oldestTaskID = this.#pendingAborts.keys().next().value!;
            clearTimeout(this.#pendingAborts.get(oldestTaskID));
            this.#pendingAborts.delete(oldestTaskID);
        }

        const timeout = setTimeout(() => this.#pendingAborts.delete(taskID), ABORT_RACE_WINDOW_MS);
        timeout.unref();
        this.#pendingAborts.set(taskID, timeout);
    }
}

const BOTS = new Map<EInternalBotType, BaseBot>();
export const registerBot = <TBot extends typeof BaseBot>(bot: TBot) => {
    if (!bot.BOT_TYPE) {
        throw new Error("Bot must have a botType property");
    }

    const botType = Utils.String.convertSafeEnum(EInternalBotType, bot.BOT_TYPE);
    BOTS.set(botType, new (bot as any)());
};

export const getBot = (botType: EInternalBotType): BaseBot | undefined => {
    botType = Utils.String.convertSafeEnum(EInternalBotType, botType);
    return BOTS.get(botType);
};

export default BaseBot;
