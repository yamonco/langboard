/* eslint-disable @typescript-eslint/no-explicit-any */
import BaseBot, { IBotIsAvailableOptions, IBotRunAbortableOptions, IBotRunOptions, IBotUploadOptions, registerBot } from "@/core/ai/BaseBot";
import { sanitizeBotTitle } from "@/core/ai/requests/utils";
import SnowflakeID from "@/core/db/SnowflakeID";
import { EInternalBotType } from "@/models/InternalBot";

class EditorChatBot extends BaseBot {
    public static get BOT_TYPE(): EInternalBotType {
        return EInternalBotType.EditorChat;
    }

    public async run({ data, ...options }: IBotRunOptions) {
        return await this.request({
            ...options,
            requestModel: {
                message: (data.messages as any[]).map((message) => `${message.role}: ${message.content}`).join("\n"),
                projectUID: data.project_uid,
                userId: data.user_id,
                inputType: "chat",
                outputType: "chat",
                tweaks: { Prompt: { prompt: data.system } },
                restData: data.rest_data,
                sessionId: `${new SnowflakeID(data.user_id).toShortCode()}-${data.project_uid}`,
            },
            useStream: true,
        });
    }

    public async runAbortable({ data, ...options }: IBotRunAbortableOptions) {
        return await this.requestAbortable({
            ...options,
            requestModel: {
                message: (data.messages as any[]).map((message) => `${message.role}: ${message.content}`).join("\n"),
                projectUID: data.project_uid,
                userId: data.user_id,
                inputType: "chat",
                outputType: "chat",
                tweaks: { Prompt: { prompt: data.system } },
                restData: data.rest_data,
                sessionId: `${new SnowflakeID(data.user_id).toShortCode()}-${data.project_uid}`,
                runId: options.taskID,
            },
            useStream: true,
        });
    }

    public async createTitle({ data, ...options }: IBotRunOptions) {
        const result = await this.request({
            ...options,
            requestModel: {
                message: data.message,
                projectUID: data.project_uid,
                userId: data.user_id,
                inputType: "chat",
                outputType: "text",
                restData: data.rest_data,
                isTitle: true,
            },
            useStream: false,
        });

        return sanitizeBotTitle(result || "");
    }

    public async isAvailable(options: IBotIsAvailableOptions): Promise<bool> {
        return await this.canRequest(options);
    }

    public async upload(options: IBotUploadOptions): Promise<string | null> {
        return await this.uploadFile(options);
    }
}

registerBot(EditorChatBot);

export default EditorChatBot;
