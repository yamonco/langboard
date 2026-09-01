/* eslint-disable @typescript-eslint/no-explicit-any */
import BotRunner from "@/core/ai/BotRunner";
import { api } from "@/core/helpers/Api";
import SnowflakeID from "@/core/db/SnowflakeID";
import EventManager from "@/core/server/EventManager";
import { Utils } from "@langboard/core/utils";
import { ESocketStatus, ESocketTopic } from "@langboard/core/enums";
import ChatHistory from "@/models/ChatHistory";
import { EInternalBotType } from "@/models/InternalBot";
import ProjectAssignedInternalBot from "@/models/ProjectAssignedInternalBot";
import { SocketEvents } from "@langboard/core/constants";
import ChatSession from "@/models/ChatSession";
import { TChatScope } from "@langboard/core/types";
import ProjectChatSession from "@/models/ProjectChatSession";
import { AGENT_PERMISSION_LEVEL_APPROVAL_POLICY, EAgentApprovalPolicy, EAgentPermissionLevel, EApiPermission } from "@langboard/core/ai";
import { createOneTimeToken } from "@/core/ai/BotOneTimeToken";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { getActiveEditorSyncDocumentNames } from "@/core/server/Hocus";
import { AI_REQUEST_TIMEOUT, DEFAULT_GRAPH_URL } from "@/Constants";
import GraphApprovalRequest from "@/models/GraphApprovalRequest";
import {
    EGraphApprovalOriginType,
    EGraphApprovalScopeTable,
    EGraphApprovalStatus,
    getGraphApprovalScopeID,
} from "@/models/GraphApprovalRequestTypes";
import ChatGraphApprovalRequest from "@/models/ChatGraphApprovalRequest";
import Subscription from "@/core/server/Subscription";
import Logger from "@/core/utils/Logger";

const parseEditorSyncDocumentName = (documentName: string) => {
    const [type, entityUID, section, ...extraParts] = documentName.split(":");
    if (!type || !entityUID || extraParts.length > 0) {
        return null;
    }

    return {
        entityUID,
        section,
        type,
    };
};

const isAgentPermissionLevel = (value: unknown): value is EAgentPermissionLevel => {
    return Object.values(EAgentPermissionLevel).some((permissionLevel) => permissionLevel === value);
};

const getCollaborativeDocumentSchema = (type: string, section?: string) => {
    if (type === EEditorCollaborationType.BoardColumnName) {
        return {
            api_field: "name",
            field: "name",
        };
    }

    if (type === EEditorCollaborationType.Card) {
        switch (section) {
            case "title":
                return { api_field: "title", field: "title" };
            case "description":
                return { api_field: "description" };
            case "deadline":
                return { api_field: "deadline_at", field: "value" };
            case "members":
                return { api_field: "assigned_users", field: "selected-member-uids" };
            case "labels":
                return { api_field: "labels", field: "selected-label-uids" };
            case "relationships-parents":
            case "relationships-children":
                return { api_field: "relationships", field: "selected-relationships" };
            default:
                if (section?.startsWith("attachment-")) {
                    return { api_field: "attachment_name", field: "name" };
                }
                if (section?.startsWith("comment-")) {
                    return { api_field: "content" };
                }
                if (section?.startsWith("checklist-")) {
                    return { api_field: "title", field: "title" };
                }
                if (section?.startsWith("checkitem-") && section.endsWith("-deadline")) {
                    return { api_field: "deadline_at", field: "value" };
                }
                if (section?.startsWith("checkitem-")) {
                    return { api_field: "title", field: "title" };
                }
                if (section?.startsWith("metadata-")) {
                    return { api_field: "metadata", field: "key/value" };
                }
        }
    }

    if (type === EEditorCollaborationType.Wiki) {
        switch (section) {
            case "title":
                return { api_field: "title", field: "title" };
            case "content":
                return { api_field: "content" };
            case "private-assignees":
                return { api_field: "assignees", field: "selected-member-uids" };
            default:
                if (section?.startsWith("metadata-")) {
                    return { api_field: "metadata", field: "key/value" };
                }
        }
    }

    if (type === EEditorCollaborationType.BotSchedule) {
        return { api_field: "schedule", field: "schedule" };
    }

    return {};
};

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
        : EGraphApprovalOriginType.Chat;
};

const toApprovalScopeTable = (value: unknown): EGraphApprovalScopeTable => {
    return Object.values(EGraphApprovalScopeTable).includes(value as EGraphApprovalScopeTable)
        ? (value as EGraphApprovalScopeTable)
        : EGraphApprovalScopeTable.Project;
};

const toRecord = (value: unknown): Record<string, unknown> => {
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
};

interface IGraphResumeInputPayload {
    approved?: bool;
    rejected?: bool;
    instruction?: string;
    reason?: string;
}

type TApprovedGraphResumeApprovalPolicy = {
    [EApiPermission.Read]: EAgentApprovalPolicy.Allow;
    [EApiPermission.Create]: EAgentApprovalPolicy.Allow;
    [EApiPermission.Edit]: EAgentApprovalPolicy.Allow;
    [EApiPermission.Delete]: EAgentApprovalPolicy.Allow;
};

interface IApprovedGraphResumePayload extends IGraphResumeInputPayload {
    approved: true;
    rejected: false;
    app_api_token: string;
    api_permission_level: EAgentPermissionLevel.FullAccess;
    api_approval_policy: TApprovedGraphResumeApprovalPolicy;
}

type TGraphResumePayload = IGraphResumeInputPayload | IApprovedGraphResumePayload;

const getActiveCollaborativeDocuments = async (projectUID: string, scopeTable: TChatScope | undefined, scopeUID: string | undefined) => {
    if (!scopeUID) {
        return [];
    }

    let type: EEditorCollaborationType | undefined;
    switch (scopeTable) {
        case "card":
            type = EEditorCollaborationType.Card;
            break;
        case "project_wiki":
            type = EEditorCollaborationType.Wiki;
            break;
        case "project_column":
            type = EEditorCollaborationType.BoardColumnName;
            break;
    }

    if (!type) {
        return [];
    }

    const lookupUID = type === EEditorCollaborationType.BoardColumnName ? projectUID : scopeUID;
    const scopedDocumentLookups = [{ type, lookupUID }];
    if (scopeTable === "card" || scopeTable === "project_column") {
        scopedDocumentLookups.push({
            type: EEditorCollaborationType.BotSchedule,
            lookupUID: projectUID,
        });
    }

    const activeDocumentNames = (
        await Promise.all(scopedDocumentLookups.map((lookup) => getActiveEditorSyncDocumentNames(lookup.type, lookup.lookupUID)))
    ).flat();
    const activeDocuments = activeDocumentNames.flatMap((documentName) => {
        const parsed = parseEditorSyncDocumentName(documentName);
        if (!parsed) {
            return [];
        }

        if (parsed.type === EEditorCollaborationType.BoardColumnName && scopeUID && parsed.section !== scopeUID) {
            return [];
        }
        if (
            parsed.type === EEditorCollaborationType.BotSchedule &&
            scopeTable &&
            scopeUID &&
            !parsed.section?.startsWith(`${scopeTable}-${scopeUID}-`)
        ) {
            return [];
        }

        return [
            {
                document_name: documentName,
                entity_uid: parsed.entityUID,
                section: parsed.section,
                type: parsed.type,
                ...getCollaborativeDocumentSchema(parsed.type, parsed.section),
            },
        ];
    });

    return activeDocuments;
};

EventManager.on(ESocketTopic.Board, SocketEvents.CLIENT.BOARD.CHAT.IS_AVAILABLE, async ({ client, topicId }) => {
    const [internalBot, _] = (await ProjectAssignedInternalBot.getInternalBotByProjectUID(EInternalBotType.ProjectChat, topicId)) ?? [null, null];
    let isAvailable = false;
    if (internalBot) {
        try {
            isAvailable = await BotRunner.isAvailable({ internalBot });
        } catch {
            isAvailable = false;
        }
    }

    const apiBot = internalBot?.apiResponse ?? null;

    client.send({
        topic: ESocketTopic.Board,
        topic_id: topicId,
        event: SocketEvents.SERVER.BOARD.CHAT.IS_AVAILABLE,
        data: { available: isAvailable, bot: apiBot },
    });
});

EventManager.on(ESocketTopic.Board, SocketEvents.CLIENT.BOARD.CHAT.SEND, async ({ client, topicId, data }) => {
    const { message, file_path, task_id, session_uid, scope_uid } = data ?? {};
    if (!Utils.Type.isString(message) || !Utils.Type.isString(task_id)) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid message data", false);
        return;
    }

    const internalBotResult = await ProjectAssignedInternalBot.getInternalBotByProjectUID(EInternalBotType.ProjectChat, topicId);
    if (!internalBotResult) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "No chat bot available for this project", false);
        return;
    }

    const [internalBot, internalBotSettings] = internalBotResult;
    const apiPermissionLevel = isAgentPermissionLevel(data?.api_permission_level) ? data.api_permission_level : EAgentPermissionLevel.Read;
    const restData: Record<string, any> = {
        project_uid: topicId,
        chat_scope: "project",
        api_permission_level: apiPermissionLevel,
        api_approval_policy: AGENT_PERMISSION_LEVEL_APPROVAL_POLICY[apiPermissionLevel],
    };

    const scopeTable = data.scope_table as TChatScope | undefined;
    const scopeUID = Utils.Type.isString(scope_uid) ? scope_uid : undefined;
    if (scopeTable) {
        restData.chat_scope = scopeTable;
        switch (scopeTable) {
            case "project_column":
                restData.project_column_uid = scopeUID;
                break;
            case "card":
                restData.card_uid = scopeUID;
                break;
            case "project_wiki":
                restData.project_wiki_uid = scopeUID;
                break;
            default:
                restData.chat_scope = "project";
                break;
        }
    }

    const activeCollaborativeDocuments = await getActiveCollaborativeDocuments(topicId, scopeTable, scopeUID);
    if (activeCollaborativeDocuments.length) {
        restData.active_collaborative_documents = activeCollaborativeDocuments;
        restData.collaborative_edit_instruction = [
            "Some fields in the current scope are being edited in real time.",
            "When changing one of those fields, use the normal matching edit API with the intended final field value.",
            "The API will automatically update the active collaborative draft instead of saving directly.",
            "Do not store unsaved draft values in metadata.",
        ].join(" ");
    }

    let chatSession: ChatSession | null = null;
    let session: ProjectChatSession | null = null;
    if (!Utils.Type.isString(session_uid) || !session_uid) {
        chatSession = await ChatSession.create({
            user_id: client.user.id,
            title: "Untitled",
            api_permission_level: apiPermissionLevel,
            last_messaged_at: new Date(),
        }).save();

        session = await ProjectChatSession.create({
            chat_session_id: chatSession.id,
            project_id: SnowflakeID.fromShortCode(topicId).toString(),
        }).save();

        client.send({
            event: SocketEvents.SERVER.BOARD.CHAT.SESSION,
            topic: ESocketTopic.Board,
            topic_id: topicId,
            data: {
                session: {
                    ...chatSession.apiResponse,
                    ...session.apiResponse,
                },
            },
        });

        void BotRunner.createTitle({
            internalBot,
            internalBotSettings,
            data: {
                message,
                user_id: client.user.id,
                project_uid: topicId,
            },
        })
            .then(async (title) => {
                title ||= "Untitled";
                if (!chatSession || !session || chatSession.title === title) {
                    return;
                }

                chatSession.title = title;
                await ChatSession.update(chatSession.id, {
                    title,
                });

                client.send({
                    event: SocketEvents.SERVER.BOARD.CHAT.SESSION,
                    topic: ESocketTopic.Board,
                    topic_id: topicId,
                    data: {
                        session: {
                            ...chatSession.apiResponse,
                            ...session.apiResponse,
                        },
                    },
                });
            })
            .catch((error) => Logger.error(error, "\n"));
    } else {
        session = await ProjectChatSession.findByUID(session_uid);
        if (!session) {
            client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid chat session model", false);
            return;
        }

        chatSession = await ChatSession.findByID(session.chat_session_id);
        if (!chatSession) {
            client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid chat session", false);
            return;
        }

        if (chatSession.api_permission_level !== apiPermissionLevel) {
            chatSession.api_permission_level = apiPermissionLevel;
            await ChatSession.update(chatSession.id, { api_permission_level: apiPermissionLevel });
        }
    }

    const userMessage = await ChatHistory.create({
        chat_session_id: chatSession.id,
        message: { content: message },
        is_received: false,
    }).save();
    await chatSession.updateLastMessagedAt(userMessage.created_at);

    restData.chat_session_uid = new SnowflakeID(chatSession.id).toShortCode();
    restData.project_chat_session_uid = session.uid;
    restData.chat_history_uid = userMessage.uid;

    client.send({
        event: SocketEvents.SERVER.BOARD.CHAT.SENT,
        topic: ESocketTopic.Board,
        topic_id: topicId,
        data: { user_message: { ...userMessage.apiResponse, chat_session_uid: session.uid } },
    });

    const response = await BotRunner.runAbortable({
        internalBot,
        internalBotSettings,
        client,
        taskID: task_id,
        data: {
            message,
            file_path,
            task_id,
            session_uid: session.uid,
            project_uid: topicId,
            user_id: client.user.id,
            rest_data: restData,
        },
    });

    if (!response) {
        client.send({
            event: SocketEvents.SERVER.BOARD.CHAT.IS_AVAILABLE,
            topic: ESocketTopic.Board,
            topic_id: topicId,
        });
        return;
    }

    const isAborted = BotRunner.createAbortedChecker(EInternalBotType.ProjectChat, task_id);
    if (isAborted()) {
        return;
    }

    const stream = client.stream(ESocketTopic.Board, topicId, SocketEvents.SERVER.BOARD.CHAT.STREAM);
    const aiMessage = await ChatHistory.create({
        chat_session_id: chatSession.id,
        message: { content: "" },
        is_received: true,
    }).save();
    await chatSession.updateLastMessagedAt(aiMessage.created_at);
    const aiMessageUID = new SnowflakeID(aiMessage.id).toShortCode();

    stream.start({ ai_message: { ...aiMessage.apiResponse, chat_session_uid: session.uid } });

    if (isAborted()) {
        return;
    }

    if (Utils.Type.isString(response)) {
        aiMessage.message = { content: response };
        stream.buffer({ uid: aiMessageUID, message: aiMessage.message });
        stream.end({ uid: aiMessageUID, status: "success" });
        await aiMessage.save();
        await chatSession.updateLastMessagedAt(aiMessage.created_at);
        return;
    }

    const newContent: { content: string; graph_interrupt?: Record<string, any> | null } = { content: "" };
    let isReceived = false;
    let lastContent: string | undefined = undefined;

    const saveMessage = async () => {
        aiMessage.message = newContent;
        await aiMessage.save();
        await chatSession.updateLastMessagedAt(aiMessage.updated_at);
    };

    await response
        .onMessage(async (chunk) => {
            isReceived = true;
            newContent.content = chunk || "";

            if (lastContent !== newContent.content) {
                stream.buffer({ uid: aiMessageUID, message: newContent });
                lastContent = newContent.content;
            }
        })
        .onInterrupt(async (interrupt) => {
            isReceived = true;
            let nextInterrupt = interrupt;
            const approvalRequest = getApprovalRequestValue(interrupt);
            if (approvalRequest) {
                const projectID = SnowflakeID.fromShortCode(topicId).toString();
                const scopeTable = toApprovalScopeTable(approvalRequest.scope_table);
                const approval = await GraphApprovalRequest.create({
                    requested_by_user_id: client.user.id,
                    resolved_by_user_id: null,
                    thread_id: String(approvalRequest.thread_id || ""),
                    run_id: String(approvalRequest.run_id || task_id),
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
                const detail = await ChatGraphApprovalRequest.create({
                    approval_request_id: approval.id,
                    scope_table: scopeTable,
                    scope_id: getGraphApprovalScopeID({
                        projectID,
                        scopeTable,
                        scopeUID: approvalRequest.scope_uid,
                    }),
                    chat_session_id: chatSession.id,
                    chat_history_id: aiMessage.id,
                }).save();
                approval.approvalResponse = detail.toGraphApprovalResponse(projectID);
                const value = {
                    ...approvalRequest,
                    approval_uid: approval.uid,
                    status: approval.status,
                };
                nextInterrupt = interrupt.value ? { ...interrupt, value } : value;
                await Subscription.publish(ESocketTopic.BoardSettings, topicId, SocketEvents.SERVER.BOARD.GRAPH_APPROVAL.REQUESTED, {
                    approval: approval.apiResponse,
                });
            }
            newContent.graph_interrupt = nextInterrupt;
            stream.buffer({ uid: aiMessageUID, interrupt: nextInterrupt });
        })
        .onError(async (error) => {
            stream.end({ uid: aiMessageUID, status: "failed", error: error.message });
            await aiMessage.remove();
        })
        .onEnd(async () => {
            if (!isReceived) {
                if (!isAborted()) {
                    stream.end({ uid: aiMessageUID, status: "failed" });
                    await aiMessage.remove();
                }

                return;
            }

            stream.end({ uid: aiMessageUID, status: isAborted() ? "aborted" : "success" });
            await saveMessage();
        })
        .stream();
});

EventManager.on(ESocketTopic.Board, SocketEvents.CLIENT.BOARD.CHAT.RESUME, async ({ client, topicId, data }) => {
    const { message_uid, thread_id, session_id, approval_uid } = data ?? {};
    if (!Utils.Type.isString(message_uid) || !Utils.Type.isString(thread_id) || !data || !("resume" in data)) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid graph resume data", false);
        return;
    }

    let messageId: string;
    let projectId: string;
    try {
        messageId = SnowflakeID.fromShortCode(message_uid).toString();
        projectId = SnowflakeID.fromShortCode(topicId).toString();
    } catch (error) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid graph resume target", false);
        return;
    }
    const aiMessage = await ChatHistory.findOne({ where: { id: messageId, is_received: true } });
    if (!aiMessage) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid graph resume message", false);
        return;
    }

    const projectChatSession = await ProjectChatSession.findOne({
        where: {
            chat_session_id: aiMessage.chat_session_id,
            project_id: projectId,
        },
    });
    if (!projectChatSession) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid graph resume session", false);
        return;
    }

    const stream = client.stream(ESocketTopic.Board, topicId, SocketEvents.SERVER.BOARD.CHAT.STREAM);
    const currentMessage = aiMessage.message ?? { content: "" };

    try {
        const resumePayload = createGraphResumePayload(data.resume, client.user.id);
        const response = await api.post(
            `${DEFAULT_GRAPH_URL}/api/v1/graph/resume/${encodeURIComponent(thread_id)}`,
            {
                resume: resumePayload,
                session_id,
            },
            {
                timeout: AI_REQUEST_TIMEOUT * 1000,
            }
        );
        const currentContent = currentMessage.content ?? "";
        const responseData = response.data ?? {};
        const isApprovedResume = !!resumePayload.approved && !resumePayload.rejected;
        const isInstructionResume = !resumePayload.approved && !resumePayload.rejected && Utils.Type.isString(resumePayload.instruction);
        const resumeInstruction = Utils.Type.isString(resumePayload.instruction) ? resumePayload.instruction : null;
        const responseMessage = Utils.Type.isString(responseData.message) ? sanitizeGraphResumeMessage(responseData.message) : "";
        const nextInterrupt = Array.isArray(responseData.interrupts) && responseData.interrupts.length > 0 ? responseData.interrupts[0] : null;

        const resolvedApproval = await resolveGraphApprovalFromChatResume({
            approvalUID: Utils.Type.isString(approval_uid) ? approval_uid : null,
            aiMessage,
            projectID: projectId,
            threadID: thread_id,
            userID: client.user.id,
            status: isApprovedResume
                ? EGraphApprovalStatus.Approved
                : isInstructionResume
                  ? EGraphApprovalStatus.Resolved
                  : EGraphApprovalStatus.Rejected,
        });
        aiMessage.message = {
            ...currentMessage,
            content: currentContent,
            graph_interrupt: nextInterrupt || createResolvedGraphInterrupt(currentMessage.graph_interrupt, resolvedApproval, resumeInstruction),
            graph_resume_error: null,
        };
        await aiMessage.save();
        await ChatSession.update(aiMessage.chat_session_id, { last_messaged_at: new Date() });

        stream.buffer({ uid: message_uid, message: aiMessage.message });
        stream.end({ uid: message_uid, status: "success" });

        if ((isApprovedResume || isInstructionResume) && responseMessage && responseMessage !== currentContent.trim()) {
            const resumedMessage = await ChatHistory.create({
                chat_session_id: aiMessage.chat_session_id,
                message: { content: responseMessage },
                is_received: true,
            }).save();
            const resumedMessageUID = new SnowflakeID(resumedMessage.id).toShortCode();
            await ChatSession.update(aiMessage.chat_session_id, { last_messaged_at: resumedMessage.created_at });

            stream.start({ ai_message: { ...resumedMessage.apiResponse, chat_session_uid: projectChatSession.uid } });
            stream.buffer({ uid: resumedMessageUID, message: resumedMessage.message });
            stream.end({ uid: resumedMessageUID, status: "success" });
        }
    } catch (error) {
        aiMessage.message = {
            ...currentMessage,
            graph_resume_error: Utils.Type.isError(error) ? error.message : "Failed to resume graph.",
        };
        await aiMessage.save();
        await ChatSession.update(aiMessage.chat_session_id, { last_messaged_at: new Date() });

        stream.buffer({ uid: message_uid, message: aiMessage.message });
        stream.end({ uid: message_uid, status: "success" });
    }
});

function createGraphResumePayload(resume: unknown, userID: string): TGraphResumePayload {
    const payload = createGraphResumeInputPayload(resume);
    if (!payload.approved || payload.rejected) {
        return payload;
    }

    return {
        ...payload,
        approved: true,
        rejected: false,
        app_api_token: createOneTimeToken(new SnowflakeID(userID), EAgentPermissionLevel.FullAccess),
        api_permission_level: EAgentPermissionLevel.FullAccess,
        api_approval_policy: {
            [EApiPermission.Read]: EAgentApprovalPolicy.Allow,
            [EApiPermission.Create]: EAgentApprovalPolicy.Allow,
            [EApiPermission.Edit]: EAgentApprovalPolicy.Allow,
            [EApiPermission.Delete]: EAgentApprovalPolicy.Allow,
        },
    };
}

function createGraphResumeInputPayload(resume: unknown): IGraphResumeInputPayload {
    if (!Utils.Type.isObject<Record<string, unknown>>(resume)) {
        return {};
    }

    const payload: IGraphResumeInputPayload = {};
    if (Utils.Type.isBool(resume.approved)) {
        payload.approved = resume.approved;
    }
    if (Utils.Type.isBool(resume.rejected)) {
        payload.rejected = resume.rejected;
    }
    if (Utils.Type.isString(resume.instruction)) {
        payload.instruction = resume.instruction;
    }
    if (Utils.Type.isString(resume.reason)) {
        payload.reason = resume.reason;
    }

    return payload;
}

function sanitizeGraphResumeMessage(message: string): string {
    return message.replace(/^Graph approval rejected(?::[^\n]*)?\.?\s*/i, "").trim();
}

function createResolvedGraphInterrupt(
    interrupt: Record<string, unknown> | null | undefined,
    approval: GraphApprovalRequest | null,
    instruction: string | null = null
) {
    if (!approval) {
        return interrupt ?? null;
    }

    const approvalRequest = interrupt ? getApprovalRequestValue(interrupt) : createApprovalRequestValueFromModel(approval);
    if (!approvalRequest) {
        return interrupt;
    }

    const value = {
        ...approvalRequest,
        approval_uid: approval.uid,
        status: approval.status,
        resolved_by_user_uid: approval.resolved_by_user_id ? new SnowflakeID(approval.resolved_by_user_id).toShortCode() : null,
        resolved_at: approval.resolved_at,
        rejection_reason: approval.rejection_reason,
        instruction,
    };

    return interrupt?.value ? { ...interrupt, value } : value;
}

function createApprovalRequestValueFromModel(approval: GraphApprovalRequest): Record<string, unknown> {
    const preview = toRecord(approval.preview_payload);
    const title = Utils.Type.isString(preview.title) ? preview.title : undefined;
    const summary = Utils.Type.isString(preview.summary) ? preview.summary : undefined;

    return {
        type: "approval_request",
        thread_id: approval.thread_id,
        run_id: approval.run_id,
        origin_type: approval.origin_type,
        scope_table: approval.approvalResponse?.scope_table,
        scope_uid: approval.approvalResponse?.scope_uid,
        document_name: approval.approvalResponse?.document_name,
        action_type: approval.action_type,
        permission: approval.permission,
        tool_name: approval.tool_name,
        api_name: approval.api_name,
        preview,
        message: summary || title || "Graph approval request resolved.",
    };
}

async function resolveGraphApprovalFromChatResume({
    approvalUID,
    aiMessage,
    projectID,
    threadID,
    userID,
    status,
}: {
    approvalUID: string | null;
    aiMessage: ChatHistory;
    projectID: string;
    threadID: string;
    userID: string;
    status: EGraphApprovalStatus;
}): Promise<GraphApprovalRequest | null> {
    let approvalID: string | null = null;
    if (approvalUID) {
        try {
            approvalID = SnowflakeID.fromShortCode(approvalUID).toString();
        } catch {
            approvalID = null;
        }
    }

    const detail = approvalID
        ? await ChatGraphApprovalRequest.findOne({
              where: {
                  approval_request_id: approvalID,
                  chat_history_id: aiMessage.id,
              },
          })
        : await ChatGraphApprovalRequest.findOne({
              where: {
                  chat_history_id: aiMessage.id,
              },
          });
    const approval = detail
        ? await GraphApprovalRequest.findOne({
              where: {
                  id: detail.approval_request_id,
                  thread_id: threadID,
                  status: EGraphApprovalStatus.Pending,
              },
          })
        : null;

    if (!approval || !detail) {
        return null;
    }

    approval.approvalResponse = detail.toGraphApprovalResponse(projectID);
    approval.status = status;
    approval.resolved_by_user_id = userID;
    approval.resolved_at = new Date();
    await approval.save();
    await Subscription.publish(
        ESocketTopic.BoardSettings,
        new SnowflakeID(projectID).toShortCode(),
        SocketEvents.SERVER.BOARD.GRAPH_APPROVAL.UPDATED,
        {
            approval: approval.apiResponse,
        }
    );
    return approval;
}

EventManager.on(ESocketTopic.Board, SocketEvents.CLIENT.BOARD.CHAT.CANCEL, async ({ client, data }) => {
    const { task_id } = data ?? {};
    if (!Utils.Type.isString(task_id)) {
        client.sendError(ESocketStatus.WS_4001_INVALID_DATA, "Invalid task ID", false);
        return;
    }

    await BotRunner.abort({ botType: EInternalBotType.ProjectChat, taskID: task_id, client });
});
