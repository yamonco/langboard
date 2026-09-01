/* eslint-disable @typescript-eslint/no-explicit-any */
import BotRunner from "@/core/ai/BotRunner";
import EventManager, { TEventContext } from "@/core/server/EventManager";
import SnowflakeID from "@/core/db/SnowflakeID";
import { Utils } from "@langboard/core/utils";
import { ESocketStatus, ESocketTopic, NONE_TOPIC_ID } from "@langboard/core/enums";
import InternalBot, { EInternalBotType } from "@/models/InternalBot";
import ProjectAssignedInternalBot, { IProjectAssignedInternalBotSettings } from "@/models/ProjectAssignedInternalBot";
import GraphApprovalRequest from "@/models/GraphApprovalRequest";
import {
    EGraphApprovalOriginType,
    EGraphApprovalScopeTable,
    EGraphApprovalStatus,
    getGraphApprovalScopeID,
} from "@/models/GraphApprovalRequestTypes";
import EditorGraphApprovalRequest from "@/models/EditorGraphApprovalRequest";
import Subscription from "@/core/server/Subscription";
import { SocketEvents } from "@langboard/core/constants";

interface IEditorEventRegistryParams {
    eventPrefix: string;
    chatType: EInternalBotType;
    copilotType: EInternalBotType;
    getInternalBot: (botType: EInternalBotType, context: TEventContext) => Promise<[InternalBot, IProjectAssignedInternalBotSettings] | [null, null]>;
    createRestData?: (context: TEventContext) => Record<string, unknown>;
}

const getApprovalRequestValue = (interrupt: Record<string, any>): Record<string, any> | null => {
    if (interrupt.type === "approval_request") {
        return interrupt;
    }

    const value = interrupt.value;
    if (value && typeof value === "object" && value.type === "approval_request") {
        return value;
    }

    return null;
};

const toApprovalOriginType = (value: unknown): EGraphApprovalOriginType => {
    return Object.values(EGraphApprovalOriginType).includes(value as EGraphApprovalOriginType)
        ? (value as EGraphApprovalOriginType)
        : EGraphApprovalOriginType.Editor;
};

const toApprovalScopeTable = (value: unknown): EGraphApprovalScopeTable => {
    return Object.values(EGraphApprovalScopeTable).includes(value as EGraphApprovalScopeTable)
        ? (value as EGraphApprovalScopeTable)
        : EGraphApprovalScopeTable.Project;
};

const toRecord = (value: unknown): Record<string, unknown> => {
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
};

const createEditorGraphApproval = async ({
    context,
    approvalRequest,
    taskID,
}: {
    context: TEventContext;
    internalBot: InternalBot;
    approvalRequest: Record<string, any>;
    taskID: string;
}): Promise<GraphApprovalRequest | null> => {
    if (!Utils.Type.isString(context.data?.project_uid)) {
        return null;
    }

    const projectID = SnowflakeID.fromShortCode(context.data.project_uid).toString();
    const scopeTable = toApprovalScopeTable(approvalRequest.scope_table);
    const documentName = Utils.Type.isString(approvalRequest.document_name) ? approvalRequest.document_name : null;
    if (!documentName) {
        return null;
    }

    const approval = await GraphApprovalRequest.create({
        requested_by_user_id: context.client.user.id,
        resolved_by_user_id: null,
        thread_id: String(approvalRequest.thread_id || ""),
        run_id: String(approvalRequest.run_id || taskID),
        request_type: toApprovalOriginType(approvalRequest.origin_type),
        action_type: Utils.Type.isString(approvalRequest.action_type) ? approvalRequest.action_type : "api_call",
        permission: Utils.Type.isString(approvalRequest.permission) ? approvalRequest.permission : "",
        tool_name: Utils.Type.isString(approvalRequest.tool_name) ? approvalRequest.tool_name : null,
        api_name: Utils.Type.isString(approvalRequest.api_name) ? approvalRequest.api_name : null,
        request_payload: toRecord(approvalRequest.request_payload),
        preview_payload: toRecord(approvalRequest.preview),
        status: EGraphApprovalStatus.Pending,
        resolved_at: null,
        expires_at: null,
        rejection_reason: null,
    }).save();
    const detail = await EditorGraphApprovalRequest.create({
        approval_request_id: approval.id,
        scope_table: scopeTable,
        scope_id: getGraphApprovalScopeID({
            projectID,
            scopeTable,
            scopeUID: approvalRequest.scope_uid,
        }),
        document_name: documentName,
    }).save();
    approval.approvalResponse = detail.toGraphApprovalResponse(projectID);

    await Subscription.publish(ESocketTopic.BoardSettings, context.data.project_uid, SocketEvents.SERVER.BOARD.GRAPH_APPROVAL.REQUESTED, {
        approval: approval.apiResponse,
    });

    return approval;
};

const registerEditorEvents = ({ eventPrefix, chatType, copilotType, getInternalBot, createRestData }: IEditorEventRegistryParams) => {
    EventManager.on(ESocketTopic.None, `${eventPrefix}:editor:chat:send`, async (context) => {
        const { task_id } = context.data ?? {};
        if (!context.data || !Utils.Type.isString(task_id)) {
            return;
        }

        const [internalBot, internalBotSettings] = await getInternalBot(chatType, context);
        if (!internalBot) {
            context.client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "No chat bot available for this project", false);
            return;
        }

        const response = await BotRunner.runAbortable({
            internalBot,
            internalBotSettings,
            client: context.client,
            taskID: task_id,
            data: {
                ...context.data,
                rest_data: createRestData ? createRestData(context) : undefined,
                user_id: context.client.user.id,
            },
        });

        const stream = context.client.stream(ESocketTopic.None, NONE_TOPIC_ID, `${eventPrefix}:editor:chat:stream`);
        stream.start();
        let message = "";
        if (!response) {
            stream.end({ message: "" });
            return;
        }

        if (Utils.Type.isString(response)) {
            stream.buffer({ message: response });
            message = response;
            stream.end({ message });
            return;
        }

        const isAborted = BotRunner.createAbortedChecker(chatType, task_id);
        if (isAborted()) {
            return;
        }

        let newContent = "";
        let lastContent: string | undefined = undefined;

        await response
            .onMessage((chunk) => {
                const oldContent = newContent;
                let updatedContent = "";
                if (chunk) {
                    if (oldContent) {
                        newContent = chunk.startsWith(oldContent) ? chunk : `${oldContent}${chunk}`;
                        updatedContent = chunk.split(oldContent, 2).pop() || chunk;
                    } else {
                        newContent = chunk;
                        updatedContent = chunk;
                    }
                }

                if (lastContent !== newContent) {
                    stream.buffer({ message: updatedContent });
                    lastContent = newContent;
                }
            })
            .onInterrupt(async (interrupt) => {
                const approvalRequest = getApprovalRequestValue(interrupt);
                if (!approvalRequest) {
                    return;
                }

                const approval = await createEditorGraphApproval({
                    context,
                    internalBot,
                    approvalRequest,
                    taskID: task_id,
                });
                if (!approval) {
                    return;
                }

                const approvalMessage = "Human approval required. Open the board Bots panel to approve or reject this editor action.";
                message = approvalMessage;
                stream.buffer({ message: approvalMessage });
            })
            .onError((error) => {
                stream.end({ status: "failed", message: error.message });
            })
            .onEnd(() => {
                stream.end({ message });
            })
            .stream();
    });

    EventManager.on(ESocketTopic.None, `${eventPrefix}:editor:chat:abort`, async (context) => {
        const { task_id } = context.data ?? {};
        if (!context.data || !Utils.Type.isString(task_id)) {
            context.client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid task ID", false);
            return;
        }

        await BotRunner.abort({ botType: chatType, taskID: task_id, client: context.client });
    });

    EventManager.on(ESocketTopic.None, `${eventPrefix}:editor:copilot:send`, async (context) => {
        const { task_id } = context.data ?? {};
        if (!context.data || !Utils.Type.isString(task_id)) {
            context.client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid task ID", false);
            return;
        }

        const [internalBot, internalBotSettings] = await getInternalBot(copilotType, context);
        if (!internalBot) {
            context.client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "No chat bot available for this project", false);
            return;
        }

        const response = await BotRunner.runAbortable({
            internalBot,
            internalBotSettings,
            client: context.client,
            taskID: task_id,
            data: {
                ...context.data,
                rest_data: createRestData ? createRestData(context) : undefined,
                user_id: context.client.user.id,
            },
        });

        const sharedData = {
            topic: ESocketTopic.None,
            topic_id: NONE_TOPIC_ID,
            event: `${eventPrefix}:editor:copilot:receive:${task_id}`,
        };

        if (!response) {
            context.client.send({
                ...sharedData,
                data: { text: "0" },
            });
            return;
        }

        if (Utils.Type.isString(response)) {
            context.client.send({
                ...sharedData,
                data: { text: response },
            });
            return;
        }

        const isAborted = BotRunner.createAbortedChecker(copilotType, task_id);
        if (isAborted()) {
            return;
        }

        let message = "";
        await response
            .onMessage((data) => {
                message = `${message}${data}`;
            })
            .onInterrupt(async (interrupt) => {
                const approvalRequest = getApprovalRequestValue(interrupt);
                if (!approvalRequest) {
                    return;
                }

                await createEditorGraphApproval({
                    context,
                    internalBot,
                    approvalRequest,
                    taskID: task_id,
                });
                message = "0";
            })
            .onError(() => {
                context.client.send({
                    ...sharedData,
                    data: { text: "0" },
                });
            })
            .onEnd(() => {
                context.client.send({
                    ...sharedData,
                    data: { text: message },
                });
            })
            .stream();
    });

    EventManager.on(ESocketTopic.None, `${eventPrefix}:editor:copilot:abort`, async (context) => {
        const { task_id } = context.data ?? {};
        if (!context.data || !Utils.Type.isString(task_id)) {
            context.client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid task ID", false);
            return;
        }

        await BotRunner.abort({ botType: chatType, taskID: task_id, client: context.client });
    });
};

interface IEditorType {
    type: string;
    getInternalBot: IEditorEventRegistryParams["getInternalBot"];
    createRestData?: IEditorEventRegistryParams["createRestData"];
}

const EDITOR_TYPES: IEditorType[] = [
    {
        type: "board:card",
        getInternalBot: async (botType, context) =>
            !Utils.Type.isString(context.data.project_uid)
                ? [null, null]
                : ((await ProjectAssignedInternalBot.getInternalBotByProjectUID(botType, context.data.project_uid)) ?? [null, null]),
        createRestData: (context) => ({
            project_uid: context.data.project_uid,
            card_uid: context.data.card_uid,
            document_name: context.data.document_name,
            origin_type: "editor",
        }),
    },
    {
        type: "board:wiki",
        getInternalBot: async (botType, context) =>
            !Utils.Type.isString(context.data.project_uid)
                ? [null, null]
                : ((await ProjectAssignedInternalBot.getInternalBotByProjectUID(botType, context.data.project_uid)) ?? [null, null]),
        createRestData: (context) => ({
            project_uid: context.data.project_uid,
            project_wiki_uid: context.data.wiki_uid,
            document_name: context.data.document_name,
            origin_type: "editor",
        }),
    },
];

for (let i = 0; i < EDITOR_TYPES.length; ++i) {
    const { type, ...params } = EDITOR_TYPES[i];
    registerEditorEvents({
        eventPrefix: type,
        chatType: EInternalBotType.EditorChat,
        copilotType: EInternalBotType.EditorCopilot,
        ...params,
    });
}
