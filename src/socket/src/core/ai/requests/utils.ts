/* eslint-disable @typescript-eslint/no-explicit-any */
import { AI_REQUEST_TIMEOUT, DEFAULT_GRAPH_URL } from "@/Constants";
import BaseRequest from "@/core/ai/requests/BaseRequest";
import DefaultRequest from "@/core/ai/requests/DefaultRequest";
import LangflowRequest from "@/core/ai/requests/LangflowRequest";
import { api } from "@/core/helpers/Api";
import Logger from "@/core/utils/Logger";
import InternalBot from "@/models/InternalBot";
import { IProjectAssignedInternalBotSettings } from "@/models/ProjectAssignedInternalBot";
import { EBotPlatform, EBotPlatformRunningType } from "@langboard/core/ai";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";

const EMPTY_BOT_STATUS_MAP = {
    project_column: {},
    card: {},
};

const isGraphConnectionRefusedError = (error: unknown): bool => {
    if (!Utils.Type.isObject(error)) {
        return false;
    }

    const target = error as {
        code?: string;
        message?: string;
        cause?: {
            code?: string;
            message?: string;
        };
    };

    if (target.code === "ECONNREFUSED" || target.cause?.code === "ECONNREFUSED") {
        return true;
    }

    return [target.message, target.cause?.message].some((message) => Utils.Type.isString(message) && message.includes("ECONNREFUSED"));
};

export const createRequest = (internalBot: InternalBot, internalBotSettings?: IProjectAssignedInternalBotSettings): BaseRequest | null => {
    internalBot.platform = Utils.String.convertSafeEnum(EBotPlatform, internalBot.platform);
    internalBot.platform_running_type = Utils.String.convertSafeEnum(EBotPlatformRunningType, internalBot.platform_running_type);

    switch (internalBot.platform) {
        case EBotPlatform.Default:
            return new DefaultRequest(internalBot, DEFAULT_GRAPH_URL, internalBotSettings);
        case EBotPlatform.Langflow:
            switch (internalBot.platform_running_type) {
                case EBotPlatformRunningType.Endpoint:
                    return new LangflowRequest(internalBot, internalBot.api_url, internalBotSettings);
                default:
                    return null;
            }
        default:
            return null;
    }
};

export const getBotStatusMap = async (projectUID: string): Promise<Record<string, any> | null> => {
    try {
        const response = await api.get(`${DEFAULT_GRAPH_URL}/bot/status/map`, {
            params: {
                project_uid: projectUID,
            },
            timeout: AI_REQUEST_TIMEOUT * 1000,
        });

        if (response.status !== EHttpStatus.HTTP_200_OK) {
            throw new Error("Graph get bot status map failed");
        }

        return {
            project_column: response.data.status_map?.project_column ?? {},
            card: response.data.status_map?.card ?? {},
        };
    } catch (error) {
        if (isGraphConnectionRefusedError(error)) {
            return EMPTY_BOT_STATUS_MAP;
        }

        Logger.error(error, "\n");
        return null;
    }
};

export const sanitizeBotTitle = (title: string): string => {
    // Remove any html tags and its content, then trim the result
    return title
        .replace("\n", "")
        .replace(/<[^>]+>[\s\S]*?<\/[^>]+>/g, "")
        .trim();
};
