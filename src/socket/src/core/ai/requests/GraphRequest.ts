/* eslint-disable @typescript-eslint/no-explicit-any */
import { api } from "@/core/helpers/Api";
import BaseRequest, { IRequestParams } from "@/core/ai/requests/BaseRequest";
import BaseStreamResponse from "@/core/ai/responses/BaseStreamResponse";
import { GraphStreamResponse } from "@/core/ai/responses/GraphResponse";
import { IBotRequestModel } from "@/core/ai/types";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import formidable from "formidable";

abstract class GraphRequest extends BaseRequest {
    protected createGraphRunURL(sessionId: string, useStream: bool): string {
        const queryParams = new URLSearchParams({
            stream: useStream ? "true" : "false",
        });

        return `${this.baseURL}/api/v1/graph/run/${encodeURIComponent(sessionId)}?${queryParams.toString()}`;
    }

    protected createChatThreadId(requestModel: IBotRequestModel, sessionId: string): string {
        const projectUID = requestModel.projectUID ?? "global";
        const parts = [this.internalBot.uid, requestModel.userId, projectUID, sessionId];
        if (requestModel.threadScope !== "session") {
            parts.push(requestModel.runId ?? sessionId);
        }
        return parts.join(":");
    }

    protected createStreamResponse({ requestModel, headers, task }: Omit<IRequestParams, "useStream">): BaseStreamResponse {
        const [abortController, finish] = task ?? [undefined, undefined];

        return new GraphStreamResponse({
            url: requestModel.url,
            headers,
            body: requestModel.reqData,
            signal: abortController?.signal,
            onEnd: finish,
        });
    }

    protected convertResponse(data: { message?: string; outputs?: Record<string, any>[] }): string {
        if (Utils.Type.isString(data.message)) {
            return data.message;
        }

        try {
            return data.outputs?.[0]?.messages?.[0]?.message ?? "";
        } catch {
            return "";
        }
    }

    public async upload(_: formidable.File): Promise<string | null> {
        return null;
    }

    public async isAvailable(): Promise<bool> {
        try {
            const healthCheck = await api.get(`${this.baseURL}/health`, {
                headers: this.getBotRequestHeaders(),
            });

            return healthCheck.status === EHttpStatus.HTTP_200_OK;
        } catch {
            return false;
        }
    }
}

export default GraphRequest;
