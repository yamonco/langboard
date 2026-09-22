import { BaseModel, IBaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { EInternalBotRunKind, EInternalBotRunStatus } from "@/core/constants/InternalBotRun";

export enum EGraphApprovalOriginType {
    Chat = "chat",
    Editor = "editor",
    Trigger = "trigger",
    Schedule = "schedule",
    ManualScopeRun = "manual_scope_run",
}

export enum EGraphApprovalScopeTable {
    Project = "project",
    ProjectColumn = "project_column",
    Card = "card",
    ProjectWiki = "project_wiki",
}

export enum EGraphApprovalStatus {
    Pending = "pending",
    Approved = "approved",
    Rejected = "rejected",
    Expired = "expired",
    Cancelled = "cancelled",
    Resolved = "resolved",
}

export interface Interface extends IBaseModel {
    project_uid: string;
    bot_uid?: string;
    internal_bot_uid?: string;
    bot_log_uid?: string;
    chat_session_uid?: string;
    chat_history_uid?: string;
    requested_by_user_uid?: string;
    resolved_by_user_uid?: string;
    thread_id: string;
    run_id: string;
    origin_type: EGraphApprovalOriginType;
    scope_table: EGraphApprovalScopeTable;
    scope_uid?: string;
    document_name?: string;
    durable_run?: boolean;
    durable_run_status?: EInternalBotRunStatus | null;
    durable_run_task_id?: string | null;
    durable_run_kind?: EInternalBotRunKind | null;
    action_type: string;
    permission: string;
    tool_name?: string;
    api_name?: string;
    preview_payload: Record<string, unknown>;
    status: EGraphApprovalStatus;
    resolved_at?: Date;
    expires_at?: Date;
    rejection_reason?: string;
}

class GraphApprovalRequestModel extends BaseModel<Interface> {
    public static get MODEL_NAME() {
        return "GraphApprovalRequestModel" as const;
    }

    public static convertModel(model: Interface): Interface {
        model.origin_type = Utils.String.convertSafeEnum(EGraphApprovalOriginType, model.origin_type);
        model.scope_table = Utils.String.convertSafeEnum(EGraphApprovalScopeTable, model.scope_table);
        model.status = Utils.String.convertSafeEnum(EGraphApprovalStatus, model.status);
        if (model.durable_run_status) {
            model.durable_run_status = Utils.String.convertSafeEnum(EInternalBotRunStatus, model.durable_run_status);
        }
        if (model.durable_run_kind) {
            model.durable_run_kind = Utils.String.convertSafeEnum(EInternalBotRunKind, model.durable_run_kind);
        }
        if (Utils.Type.isString(model.resolved_at)) {
            model.resolved_at = new Date(model.resolved_at);
        }
        if (Utils.Type.isString(model.expires_at)) {
            model.expires_at = new Date(model.expires_at);
        }
        return model;
    }

    public get project_uid() {
        return this.getValue("project_uid");
    }
    public get thread_id() {
        return this.getValue("thread_id");
    }
    public get run_id() {
        return this.getValue("run_id");
    }
    public get origin_type() {
        return this.getValue("origin_type");
    }
    public get scope_table() {
        return this.getValue("scope_table");
    }
    public get scope_uid() {
        return this.getValue("scope_uid");
    }
    public get document_name() {
        return this.getValue("document_name");
    }
    public get durable_run() {
        return this.getValue("durable_run");
    }
    public get durable_run_status() {
        return this.getValue("durable_run_status");
    }
    public get durable_run_task_id() {
        return this.getValue("durable_run_task_id");
    }
    public get durable_run_kind() {
        return this.getValue("durable_run_kind");
    }
    public get action_type() {
        return this.getValue("action_type");
    }
    public get tool_name() {
        return this.getValue("tool_name");
    }
    public get api_name() {
        return this.getValue("api_name");
    }
    public get preview_payload() {
        return this.getValue("preview_payload");
    }
    public get resolved_by_user_uid() {
        return this.getValue("resolved_by_user_uid");
    }
    public get status() {
        return this.getValue("status");
    }
    public set status(value) {
        this.update({ status: value });
    }
    public get resolved_at() {
        return this.getValue("resolved_at");
    }
    public get rejection_reason() {
        return this.getValue("rejection_reason");
    }
}

registerModel(GraphApprovalRequestModel);

export const Model = GraphApprovalRequestModel;
export type TModel = GraphApprovalRequestModel;
