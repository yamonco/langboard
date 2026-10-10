import useCardCheckitemCreatedHandlers from "@/controllers/socket/card/checkitem/useCardCheckitemCreatedHandlers";
import useCardCheckitemDeletedHandlers from "@/controllers/socket/card/checkitem/useCardCheckitemDeletedHandlers";
import { BaseModel, IBaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import * as ProjectCheckitem from "@/core/models/ProjectCheckitem";

export interface Interface extends IBaseModel {
    card_uid: string;
    title: string;
    order: number;
    is_checked: bool;
}

export interface IStore extends Interface {
    checkitems?: ProjectCheckitem.Interface[];

    // variable set from the client side
    isOpenedInBoardCard: bool;
}

class ProjectChecklist extends BaseModel<IStore> {
    public static override get FOREIGN_MODELS() {
        return {
            checkitems: ProjectCheckitem.Model.MODEL_NAME,
        };
    }
    override get FOREIGN_MODELS() {
        return ProjectChecklist.FOREIGN_MODELS;
    }
    public static get MODEL_NAME() {
        return "ProjectChecklist" as const;
    }

    constructor(model: Record<string, unknown>) {
        super({ ...model, isOpenedInBoardCard: model.isOpenedInBoardCard ?? true });

        this.subscribeSocketEvents([useCardCheckitemCreatedHandlers, useCardCheckitemDeletedHandlers], {
            cardUID: this.card_uid,
            checklistUID: this.uid,
            checklist: this,
        });
    }

    public get card_uid() {
        return this.getValue("card_uid");
    }
    public set card_uid(value) {
        this.update({ card_uid: value });
    }

    public get title() {
        return this.getValue("title");
    }
    public set title(value) {
        this.update({ title: value });
    }

    public get order() {
        return this.getValue("order");
    }
    public set order(value) {
        this.update({ order: value });
    }

    public get checkitems(): ProjectCheckitem.TModel[] {
        return this.getForeignValue("checkitems");
    }
    public set checkitems(value: (ProjectCheckitem.TModel | ProjectCheckitem.Interface)[]) {
        this.update({ checkitems: value });
    }

    public get is_checked() {
        return this.getValue("is_checked");
    }
    public set is_checked(value) {
        this.update({ is_checked: value });
    }

    public get isOpenedInBoardCard() {
        return this.getValue("isOpenedInBoardCard") ?? true;
    }
    public set isOpenedInBoardCard(value) {
        this.update({ isOpenedInBoardCard: value });
    }
}

registerModel(ProjectChecklist);

export type TModel = ProjectChecklist;
export const Model = ProjectChecklist;
