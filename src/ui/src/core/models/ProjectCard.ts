import * as ProjectCardRelationship from "@/core/models/ProjectCardRelationship";
import * as ProjectLabel from "@/core/models/ProjectLabel";
import * as User from "@/core/models/User";
import useCardAssignedUsersUpdatedHandlers from "@/controllers/socket/card/useCardAssignedUsersUpdatedHandlers";
import useCardColumnChangedHandlers from "@/controllers/socket/card/useCardColumnChangedHandlers";
import useCardDeletedHandlers from "@/controllers/socket/card/useCardDeletedHandlers";
import useCardDetailsChangedHandlers from "@/controllers/socket/card/useCardDetailsChangedHandlers";
import useCardLabelsUpdatedHandlers from "@/controllers/socket/card/useCardLabelsUpdatedHandlers";
import useCardProjectUsersUpdatedHandlers from "@/controllers/socket/card/useCardProjectUsersUpdatedHandlers";
import useCardAttachmentDeletedHandlers from "@/controllers/socket/card/attachment/useCardAttachmentDeletedHandlers";
import useCardAttachmentUploadedHandlers from "@/controllers/socket/card/attachment/useCardAttachmentUploadedHandlers";
import useCardChecklistCheckedChangedHandlers from "@/controllers/socket/card/checklist/useCardChecklistCheckedChangedHandlers";
import useCardChecklistCreatedHandlers from "@/controllers/socket/card/checklist/useCardChecklistCreatedHandlers";
import useCardChecklistDeletedHandlers from "@/controllers/socket/card/checklist/useCardChecklistDeletedHandlers";
import useCardChecklistTitleChangedHandlers from "@/controllers/socket/card/checklist/useCardChecklistTitleChangedHandlers";
import useCardCommentAddedHandlers from "@/controllers/socket/card/comment/useCardCommentAddedHandlers";
import useCardCommentDeletedHandlers from "@/controllers/socket/card/comment/useCardCommentDeletedHandlers";
import useCardCommentReactedHandlers from "@/controllers/socket/card/comment/useCardCommentReactedHandlers";
import useMetadataDeletedHandlers from "@/controllers/socket/metadata/useMetadataDeletedHandlers";
import useMetadataUpdatedHandlers from "@/controllers/socket/metadata/useMetadataUpdatedHandlers";
import { BaseModel, IBaseModel, IEditorContent } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { ProjectRole } from "@/core/models/roles";

export interface Interface extends IBaseModel {
    project_uid: string;
    project_column_uid: string;
    title: string;
    description: IEditorContent;
    ai_description?: string;
    order: number;
    deadline_at?: Date;
    archived_at?: Date;
    can_delete?: bool;
    source_type?: "project_wiki" | (string & {});
    source_uid?: string;
    linked_resource?: {
        type: "project_wiki" | (string & {});
        uid: string;
        status: "available" | "forbidden" | "missing";
        title?: string;
        preview?: string;
        content?: IEditorContent;
    };
}

export interface IStore extends Interface {
    count_comment: number;
    member_uids: string[];
    project_column_name: string;
    current_auth_role_actions: ProjectRole.TActions[];
    project_members: User.Interface[];
    labels: ProjectLabel.Interface[];
    relationships: ProjectCardRelationship.Interface[];

    // variable set from the client side
    isCollapseOpened?: bool;
}

class ProjectCard extends BaseModel<IStore> {
    public static override get FOREIGN_MODELS() {
        return {
            project_members: User.Model.MODEL_NAME,
            labels: ProjectLabel.Model.MODEL_NAME,
            relationships: ProjectCardRelationship.Model.MODEL_NAME,
        };
    }
    override get FOREIGN_MODELS() {
        return ProjectCard.FOREIGN_MODELS;
    }
    public static get MODEL_NAME() {
        return "ProjectCard" as const;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        const cardSocketHandlers =
            this.source_type === "project_wiki"
                ? [useCardColumnChangedHandlers, useCardDeletedHandlers]
                : [
                      useCardDetailsChangedHandlers,
                      useCardCommentAddedHandlers,
                      useCardCommentDeletedHandlers,
                      useCardCommentReactedHandlers,
                      useCardProjectUsersUpdatedHandlers,
                      useCardAssignedUsersUpdatedHandlers,
                      useCardLabelsUpdatedHandlers,
                      useCardChecklistCreatedHandlers,
                      useCardChecklistTitleChangedHandlers,
                      useCardChecklistCheckedChangedHandlers,
                      useCardChecklistDeletedHandlers,
                      useCardAttachmentUploadedHandlers,
                      useCardAttachmentDeletedHandlers,
                      useCardColumnChangedHandlers,
                      useCardDeletedHandlers,
                  ];

        this.subscribeSocketEvents(cardSocketHandlers, {
            projectUID: this.project_uid,
            uid: this.uid,
            cardUID: this.uid,
            card: this,
        });

        if (this.source_type !== "project_wiki") {
            this.subscribeSocketEvents([useMetadataUpdatedHandlers, useMetadataDeletedHandlers], {
                type: "card",
                uid: this.uid,
            });
        }
    }

    public static convertModel(model: IStore): IStore {
        if (model.source_type === "project_wiki") {
            model.title = model.linked_resource?.status === "available" ? (model.linked_resource.title ?? "") : "";
        }
        if (Utils.Type.isString(model.deadline_at)) {
            model.deadline_at = new Date(model.deadline_at);
        }
        if (Utils.Type.isString(model.archived_at)) {
            model.archived_at = new Date(model.archived_at);
        }
        return model;
    }

    public get project_uid() {
        return this.getValue("project_uid");
    }
    public set project_uid(value) {
        this.update({ project_uid: value });
    }

    public get project_column_uid() {
        return this.getValue("project_column_uid");
    }
    public set project_column_uid(value) {
        this.update({ project_column_uid: value });
    }

    public get title() {
        return this.getValue("title");
    }

    public get source_type() {
        return this.getValue("source_type");
    }

    public get source_uid() {
        return this.getValue("source_uid");
    }

    public get linked_resource() {
        return this.getValue("linked_resource");
    }
    public set title(value) {
        this.update({ title: value });
    }

    public get description() {
        return this.getValue("description");
    }
    public set description(value) {
        this.update({ description: value });
    }

    public get order() {
        return this.getValue("order");
    }
    public set order(value) {
        this.update({ order: value });
    }

    public get archived_at(): Date | undefined {
        return this.getValue("archived_at");
    }

    public get can_delete() {
        return this.getValue("can_delete") ?? false;
    }
    public set archived_at(value: string | Date | undefined) {
        this.update({ archived_at: value as unknown as Date });
    }

    public get count_comment() {
        return this.getValue("count_comment");
    }
    public set count_comment(value) {
        this.update({ count_comment: value });
    }

    public get member_uids() {
        return this.getValue("member_uids");
    }
    public set member_uids(value) {
        this.update({ member_uids: value });
    }

    public get deadline_at(): Date | undefined {
        return this.getValue("deadline_at");
    }
    public set deadline_at(value: string | Date | undefined) {
        this.update({ deadline_at: value as unknown as Date });
    }

    public get project_column_name() {
        return this.getValue("project_column_name");
    }
    public set project_column_name(value) {
        this.update({ project_column_name: value });
    }

    public get current_auth_role_actions() {
        return this.getValue("current_auth_role_actions");
    }
    public set current_auth_role_actions(value) {
        this.update({ current_auth_role_actions: value });
    }

    public get project_members(): User.TModel[] {
        return this.getForeignValue("project_members");
    }
    public set project_members(value: (User.TModel | User.Interface)[]) {
        this.update({ project_members: value });
    }

    public get labels(): ProjectLabel.TModel[] {
        return this.getForeignValue("labels");
    }
    public set labels(value: (ProjectLabel.TModel | ProjectLabel.Interface)[]) {
        this.update({ labels: value });
    }

    public get relationships(): ProjectCardRelationship.TModel[] {
        return this.getForeignValue("relationships");
    }
    public set relationships(value: (ProjectCardRelationship.TModel | ProjectCardRelationship.Interface)[]) {
        this.update({ relationships: value });
    }
}

registerModel(ProjectCard);

export type TModel = ProjectCard;
export const Model = ProjectCard;
