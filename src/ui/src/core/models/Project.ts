import * as User from "@/core/models/User";
import * as ProjectLabel from "@/core/models/ProjectLabel";
import * as InternalBotModel from "@/core/models/InternalBotModel";
import useBoardAssignedInternalBotSettingsChangedHandlers from "@/controllers/socket/board/useBoardAssignedInternalBotSettingsChangedHandlers";
import useBoardAssignedUsersUpdatedHandlers from "@/controllers/socket/board/useBoardAssignedUsersUpdatedHandlers";
import useBoardBotStatusChangedHandlers from "@/controllers/socket/board/useBoardBotStatusChangedHandlers";
import useBoardDetailsChangedHandlers from "@/controllers/socket/board/useBoardDetailsChangedHandlers";
import useBoardUserRolesUpdatedHandlers from "@/controllers/socket/board/useBoardUserRolesUpdatedHandlers";
import useBoardBotLogCreatedHandlers from "@/controllers/socket/board/botLogs/useBoardBotLogCreatedHandlers";
import useBoardBotLogStackAddedHandlers from "@/controllers/socket/board/botLogs/useBoardBotLogStackAddeddHandlers";
import useBoardBotCronRescheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronRescheduledHandlers";
import useBoardBotCronScheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronScheduledHandlers";
import useBoardBotCronUnscheduledHandlers from "@/controllers/socket/board/botSchedules/useBoardBotCronUnscheduledHandlers";
import useBoardBotScopeCreatedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeCreatedHandlers";
import useBoardBotScopeDeletedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeDeletedHandlers";
import useBoardBotScopeTriggerConditionsUpdatedHandlers from "@/controllers/socket/board/botScopes/useBoardBotScopeTriggerConditionsUpdatedHandlers";
import useBoardChatTemplateCreatedHandlers from "@/controllers/socket/board/chat/useBoardChatTemplateCreatedHandlers";
import useBoardColumnCreatedHandlers from "@/controllers/socket/board/column/useBoardColumnCreatedHandlers";
import useBoardColumnNameChangedHandlers from "@/controllers/socket/board/column/useBoardColumnNameChangedHandlers";
import useBoardLabelCreatedHandlers from "@/controllers/socket/board/label/useBoardLabelCreatedHandlers";
import useBoardLabelDeletedHandlers from "@/controllers/socket/board/label/useBoardLabelDeletedHandlers";
import useCardRelationshipsUpdatedHandlers from "@/controllers/socket/card/useCardRelationshipsUpdatedHandlers";
import useDashboardCardCreatedHandlers from "@/controllers/socket/dashboard/card/useDashboardCardCreatedHandlers";
import useDashboardCardDeletedHandlers from "@/controllers/socket/dashboard/card/useDashboardCardDeletedHandlers";
import useDashboardCardOrderChangedHandlers from "@/controllers/socket/dashboard/card/useDashboardCardOrderChangedHandlers";
import useDashboardCardTitleChangedHandlers from "@/controllers/socket/dashboard/card/useDashboardCardTitleChangedHandlers";
import useDashboardCheckitemCheckedChangedHandlers from "@/controllers/socket/dashboard/checkitem/useDashboardCheckitemCheckedChangedHandlers";
import useDashboardCheckitemDeletedHandlers from "@/controllers/socket/dashboard/checkitem/useDashboardCheckitemDeletedHandlers";
import useDashboardCheckitemStatusChangedHandlers from "@/controllers/socket/dashboard/checkitem/useDashboardCheckitemStatusChangedHandlers";
import useDashboardCheckitemTitleChangedHandlers from "@/controllers/socket/dashboard/checkitem/useDashboardCheckitemTitleChangedHandlers";
import useDashboardProjectAssignedUsersUpdatedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectAssignedUsersUpdatedHandlers";
import useDashboardProjectColumnCreatedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectColumnCreatedHandlers";
import useDashboardProjectColumnDeletedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectColumnDeletedHandlers";
import useDashboardProjectColumnNameChangedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectColumnNameChangedHandlers";
import useDashboardProjectColumnOrderChangedHandlers from "@/controllers/socket/dashboard/project/useDashboardProjectColumnOrderChangedHandlers";
import useProjectDeletedHandlers from "@/controllers/socket/shared/useProjectDeletedHandlers";
import { IBaseModel, BaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { ProjectRole } from "@/core/models/roles";

export const TYPES = ["SI", "SW", "Other"];

export interface Interface extends IBaseModel {
    owner_uid: string;
    title: string;
    project_type: string;
}

export interface IStore extends Interface {
    all_members: User.Interface[];
    invited_member_uids: string[];
    starred: bool;
    internal_bots: InternalBotModel.Interface[];
    internal_bot_settings: Record<
        InternalBotModel.EInternalBotType,
        {
            prompt: string;
            use_default_prompt: bool;
        }
    >;
    current_auth_role_actions: ProjectRole.TActions[];
    labels: ProjectLabel.Interface[];
    description: string;
    ai_description?: string;
    last_viewed_at: Date;

    member_roles: Record<string, ProjectRole.TActions[]>; // This will be used in board setting.
    access_groups: {
        uid: string;
        role_key: "owner" | "contributor" | "viewer";
        name: string;
        description: string;
        member_uids: string[];
        member_count: number;
    }[];
}

class Project extends BaseModel<IStore> {
    public static override get FOREIGN_MODELS() {
        return {
            all_members: User.Model.MODEL_NAME,
            internal_bots: InternalBotModel.Model.MODEL_NAME,
            labels: ProjectLabel.Model.MODEL_NAME,
        };
    }
    override get FOREIGN_MODELS() {
        return Project.FOREIGN_MODELS;
    }
    public static get MODEL_NAME() {
        return "Project" as const;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        this.subscribeSocketEvents(
            [
                useBoardColumnCreatedHandlers,
                useBoardColumnNameChangedHandlers,
                useBoardDetailsChangedHandlers,
                useBoardAssignedUsersUpdatedHandlers,
                useBoardUserRolesUpdatedHandlers,
                useBoardLabelCreatedHandlers,
                useBoardLabelDeletedHandlers,
                useCardRelationshipsUpdatedHandlers,
                useBoardChatTemplateCreatedHandlers,
                useBoardBotScopeCreatedHandlers,
                useBoardBotScopeTriggerConditionsUpdatedHandlers,
                useBoardBotScopeDeletedHandlers,
                useBoardBotCronScheduledHandlers,
                useBoardBotCronRescheduledHandlers,
                useBoardBotCronUnscheduledHandlers,
                useBoardBotLogCreatedHandlers,
                useBoardBotLogStackAddedHandlers,
                useDashboardProjectAssignedUsersUpdatedHandlers,
                useDashboardProjectColumnCreatedHandlers,
                useDashboardProjectColumnNameChangedHandlers,
                useDashboardProjectColumnOrderChangedHandlers,
                useDashboardProjectColumnDeletedHandlers,
                useDashboardCardCreatedHandlers,
                useDashboardCardOrderChangedHandlers,
                useDashboardCardTitleChangedHandlers,
                useDashboardCardDeletedHandlers,
                useDashboardCheckitemTitleChangedHandlers,
                useDashboardCheckitemStatusChangedHandlers,
                useDashboardCheckitemCheckedChangedHandlers,
                useDashboardCheckitemDeletedHandlers,
                useProjectDeletedHandlers,
                useBoardBotStatusChangedHandlers,
                useBoardAssignedInternalBotSettingsChangedHandlers,
            ],
            {
                projectUID: this.uid,
                project: this,
            }
        );
    }

    public static convertModel(model: IStore): Interface {
        if (Utils.Type.isString(model.last_viewed_at)) {
            model.last_viewed_at = new Date(model.last_viewed_at);
        }

        if (!Utils.Type.isNullOrUndefined(model.internal_bot_settings)) {
            const newSettings = {} as IStore["internal_bot_settings"];
            Object.entries(model.internal_bot_settings).forEach(([key, value]) => {
                key = Utils.String.convertSafeEnum(InternalBotModel.EInternalBotType, key);
                newSettings[key] = value;
            });
            model.internal_bot_settings = newSettings;
        }
        return model;
    }

    public get owner_uid() {
        return this.getValue("owner_uid");
    }
    public set owner_uid(value) {
        this.update({ owner_uid: value });
    }

    public get title() {
        return this.getValue("title");
    }
    public set title(value) {
        this.update({ title: value });
    }

    public get project_type() {
        return this.getValue("project_type");
    }
    public set project_type(value) {
        this.update({ project_type: value });
    }

    public get starred() {
        return this.getValue("starred");
    }
    public set starred(value) {
        this.update({ starred: value });
    }

    public get description() {
        return this.getValue("description");
    }
    public set description(value) {
        this.update({ description: value });
    }

    public get ai_description() {
        return this.getValue("ai_description");
    }
    public set ai_description(value) {
        this.update({ ai_description: value });
    }

    public get all_members(): User.TModel[] {
        return this.getForeignValue("all_members");
    }
    public set all_members(value: (User.TModel | User.Interface)[]) {
        this.update({ all_members: value });
    }

    public get invited_member_uids() {
        return this.getValue("invited_member_uids");
    }
    public set invited_member_uids(value) {
        this.update({ invited_member_uids: value });
    }

    public get internal_bots(): InternalBotModel.TModel[] {
        return this.getForeignValue("internal_bots");
    }
    public set internal_bots(value: (InternalBotModel.TModel | InternalBotModel.Interface)[]) {
        this.update({ internal_bots: value });
    }

    public get internal_bot_settings() {
        return this.getValue("internal_bot_settings");
    }
    public set internal_bot_settings(value) {
        this.update({ internal_bot_settings: value });
    }

    public get current_auth_role_actions() {
        return this.getValue("current_auth_role_actions");
    }
    public set current_auth_role_actions(value) {
        this.update({ current_auth_role_actions: value });
    }

    public get labels(): ProjectLabel.TModel[] {
        return this.getForeignValue("labels");
    }
    public set labels(value: (ProjectLabel.TModel | ProjectLabel.Interface)[]) {
        this.update({ labels: value });
    }

    public get last_viewed_at(): Date {
        return this.getValue("last_viewed_at");
    }
    public set last_viewed_at(value: string | Date) {
        this.update({ last_viewed_at: value as unknown as Date });
    }

    public get member_roles() {
        return this.getValue("member_roles");
    }
    public set member_roles(value) {
        this.update({ member_roles: value });
    }

    public get access_groups() {
        return this.getValue("access_groups");
    }
    public set access_groups(value) {
        this.update({ access_groups: value });
    }
}

registerModel(Project);

export type TModel = Project;
export const Model = Project;
