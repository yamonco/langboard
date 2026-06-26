import BaseBot, { IBotIsAvailableOptions, IBotRunAbortableOptions, IBotRunOptions, IBotUploadOptions, registerBot } from "@/core/ai/BaseBot";
import { sanitizeBotTitle } from "@/core/ai/requests/utils";
import SnowflakeID from "@/core/db/SnowflakeID";
import { EInternalBotType } from "@/models/InternalBot";

class ProjectChatBot extends BaseBot {
    public static get BOT_TYPE(): EInternalBotType {
        return EInternalBotType.ProjectChat;
    }

    public async run({ data, ...options }: IBotRunOptions) {
        const sessionId = this.createSessionId(data);
        return await this.request({
            ...options,
            requestModel: {
                message: data.message,
                projectUID: data.project_uid,
                userId: data.user_id,
                inputType: "chat",
                outputType: "chat",
                tweaks: {},
                restData: data.rest_data,
                sessionId,
                runId: data.task_id,
                threadScope: "session",
                filePath: data.file_path,
            },
            useStream: true,
        });
    }

    public async runAbortable({ data, ...options }: IBotRunAbortableOptions) {
        const sessionId = this.createSessionId(data);
        return await this.requestAbortable({
            ...options,
            requestModel: {
                message: data.message,
                projectUID: data.project_uid,
                userId: data.user_id,
                inputType: "chat",
                outputType: "chat",
                tweaks: {},
                restData: data.rest_data,
                sessionId,
                runId: data.task_id,
                threadScope: "session",
                filePath: data.file_path,
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

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    private createSessionId(data: Record<string, any>): string {
        return data.session_uid || `${new SnowflakeID(data.user_id).toShortCode()}-${data.project_uid}`;
    }
}

registerBot(ProjectChatBot);

export default ProjectChatBot;
