/* eslint-disable @typescript-eslint/no-explicit-any */
import { OLLAMA_API_URL } from "@/Constants";
import { LangboardCalledAPIToolsComponent, LangboardCalledVariablesComponent, LangboardFile } from "@/core/ai/helpers/TweaksComponent";
import { createApiComfortToolPrompt, expandApiNamesWithComfortTools, IApiComfortTool } from "@/core/ai/helpers/ApiComfortTools";
import { createOneTimeToken } from "@/core/ai/BotOneTimeToken";
import { IRequestData, IRequestExecuteParams } from "@/core/ai/requests/BaseRequest";
import GraphRequest from "@/core/ai/requests/GraphRequest";
import { IBotRequestModel } from "@/core/ai/types";
import SnowflakeID from "@/core/db/SnowflakeID";
import { Utils } from "@langboard/core/utils";
import { EAgentPermissionLevel } from "@langboard/core/ai";

class DefaultRequest extends GraphRequest {
    protected createRequestData({ requestModel, useStream }: IRequestExecuteParams): IRequestData | null {
        const sessionId = requestModel.sessionId ?? Utils.String.Token.generate(32);
        const apiPermissionLevel = requestModel.restData?.api_permission_level ?? EAgentPermissionLevel.Read;
        const oneTimeToken = createOneTimeToken(new SnowflakeID(requestModel.userId), apiPermissionLevel);

        requestModel.tweaks = requestModel.tweaks ?? {};

        if (requestModel.filePath) {
            requestModel.tweaks = {
                ...requestModel.tweaks,
                ...new LangboardFile(requestModel.filePath).toTweaks(),
            };
        }

        const components = [
            new LangboardCalledVariablesComponent(
                "chat",
                oneTimeToken,
                "user",
                { uid: new SnowflakeID(requestModel.userId).toShortCode() },
                requestModel.projectUID,
                requestModel.restData
            ),
        ];

        const tweaks = {
            ...requestModel.tweaks,
            ...components.reduce((acc, component) => ({ ...acc, ...component.toTweaks(), ...component.toData() }), {}),
        };

        const reqData = {
            input_value: requestModel.message,
            input_type: requestModel.inputType,
            output_type: requestModel.outputType,
            session: sessionId,
            session_id: sessionId,
            thread_id: this.createChatThreadId(requestModel, sessionId),
            run_type: "internal_bot",
            uid: this.internalBot.uid,
            tweaks: this.#setGraphOptions(requestModel, tweaks),
        };

        return {
            url: this.createGraphRunURL(sessionId, !!useStream),
            oneTimeToken,
            reqData,
        };
    }

    #setGraphOptions(requestModel: IBotRequestModel, tweaks: Record<string, any>) {
        try {
            const botValue: Record<string, any> = Utils.Json.Parse(this.internalBot.value ?? "{}");

            const agentLLM = Utils.Type.isString(botValue.agent_llm) ? botValue.agent_llm : "";
            delete botValue.agent_llm;

            const configuredApiNames = Array.isArray(botValue.api_names)
                ? botValue.api_names.filter((apiName): apiName is string => Utils.Type.isString(apiName))
                : [];
            const configuredSystemPrompt = Utils.Type.isString(botValue.system_prompt) ? botValue.system_prompt : "";
            const approvalRequest = botValue.approval_request;
            const configuredApiApprovalPolicy = Utils.Type.isObject(botValue.api_approval_policy) ? botValue.api_approval_policy : undefined;
            const requestApiApprovalPolicy = Utils.Type.isObject(requestModel.restData?.api_approval_policy)
                ? requestModel.restData.api_approval_policy
                : undefined;
            const comfortToolNames = Array.isArray(botValue.comfort_tool_names)
                ? botValue.comfort_tool_names.filter((comfortToolName): comfortToolName is string => Utils.Type.isString(comfortToolName))
                : [];
            const comfortToolDescriptions =
                botValue.comfort_tool_descriptions && Utils.Type.isObject(botValue.comfort_tool_descriptions)
                    ? (botValue.comfort_tool_descriptions as Record<string, string>)
                    : {};
            const comfortToolDefinitions =
                botValue.comfort_tool_definitions && Utils.Type.isObject(botValue.comfort_tool_definitions)
                    ? (botValue.comfort_tool_definitions as Record<string, IApiComfortTool>)
                    : {};
            delete botValue.comfort_tool_names;
            delete botValue.comfort_tool_descriptions;
            delete botValue.comfort_tool_definitions;
            delete botValue.api_names;
            delete botValue.system_prompt;
            delete botValue.approval_request;
            delete botValue.api_approval_policy;

            if (botValue.base_url === "default") {
                botValue.base_url = OLLAMA_API_URL;
            }

            const comfortToolPrompt = createApiComfortToolPrompt(comfortToolNames, comfortToolDescriptions, comfortToolDefinitions);
            let systemPrompt = "";
            if (requestModel.isTitle) {
                systemPrompt = this.getTitlePrompt();
            } else if (this.internalBotSettings && !this.internalBotSettings.use_default_prompt) {
                systemPrompt = this.internalBotSettings.prompt;
            } else {
                systemPrompt = configuredSystemPrompt;
            }

            if (!requestModel.isTitle && comfortToolPrompt) {
                systemPrompt = [systemPrompt, comfortToolPrompt].filter(Boolean).join("\n\n");
            }

            const apiNames = expandApiNamesWithComfortTools(configuredApiNames, comfortToolNames, comfortToolDefinitions);
            if (apiNames.length) {
                const apiToolsComponent = new LangboardCalledAPIToolsComponent(apiNames);
                tweaks[LangboardCalledVariablesComponent.name].api_names = apiNames;
                tweaks = { ...tweaks, ...apiToolsComponent.toTweaks(), ...apiToolsComponent.toData() };
            }

            tweaks.Graph = {
                agent_llm: agentLLM,
                settings: botValue,
                system_prompt: systemPrompt,
                api_names: apiNames,
            };
            if (requestApiApprovalPolicy ?? configuredApiApprovalPolicy) {
                tweaks.Graph.api_approval_policy = requestApiApprovalPolicy ?? configuredApiApprovalPolicy;
            }
            if (approvalRequest) {
                tweaks.Graph.approval_request = approvalRequest;
            }
        } catch {
            // Invalid bot values are handled by the graph runtime response/logging path.
        }

        return tweaks;
    }
}

export default DefaultRequest;
