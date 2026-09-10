import * as BotModel from "@/core/models/BotModel";
import * as User from "@/core/models/User";
import { BaseModel, IBaseModel, IEditorContent } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import { TReactionEmoji } from "@/components/ReactionCounter";
import type { ICardCommentAnchor } from "@/core/models/types/card-comment-anchor.type";

export interface Interface extends IBaseModel {
    card_uid: string;
    content: IEditorContent;
    is_edited: bool;
    anchor?: ICardCommentAnchor | null;
}

export interface IStore extends Interface {
    user?: User.Interface;
    bot?: BotModel.Interface;
    reactions: Partial<Record<TReactionEmoji, string[]>>;
}

class ProjectCardComment extends BaseModel<IStore> {
    public static override get FOREIGN_MODELS() {
        return {
            user: User.Model.MODEL_NAME,
            bot: BotModel.Model.MODEL_NAME,
        };
    }
    override get FOREIGN_MODELS() {
        return ProjectCardComment.FOREIGN_MODELS;
    }
    public static get MODEL_NAME() {
        return "ProjectCardComment" as const;
    }

    public get card_uid() {
        return this.getValue("card_uid");
    }
    public set card_uid(value) {
        this.update({ card_uid: value });
    }

    public get content() {
        return this.getValue("content");
    }
    public set content(value) {
        this.update({ content: value });
    }

    public get is_edited() {
        return this.getValue("is_edited");
    }

    public get anchor() {
        return this.getValue("anchor");
    }
    public set anchor(value) {
        this.update({ anchor: value });
    }
    public set is_edited(value) {
        this.update({ is_edited: value });
    }

    public get user(): User.TModel | undefined {
        return this.getForeignValue("user")[0];
    }
    public set user(value: User.TModel | User.Interface) {
        this.update({ user: value });
    }

    public get bot(): BotModel.TModel | undefined {
        return this.getForeignValue("bot")[0];
    }
    public set bot(value: BotModel.TModel | BotModel.Interface) {
        this.update({ bot: value });
    }

    public get reactions() {
        return this.getValue("reactions");
    }
    public set reactions(value) {
        this.update({ reactions: value });
    }
}

registerModel(ProjectCardComment);

export type TModel = ProjectCardComment;
export const Model = ProjectCardComment;
