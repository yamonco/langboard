import useBoardLabelDetailsChangedHandlers from "@/controllers/socket/board/label/useBoardLabelDetailsChangedHandlers";
import { BaseModel, IBaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";

export interface Interface extends IBaseModel {
    project_uid: string;
    name: string;
    color: string;
    description: string;
    order: number;
    global_label_uid?: string | null;
    global_display?: { emoji?: string; translations: Record<string, { name: string; description: string }> } | null;
}

class ProjectLabel extends BaseModel<Interface> {
    public static get MODEL_NAME() {
        return "ProjectLabel" as const;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        this.subscribeSocketEvents([useBoardLabelDetailsChangedHandlers], {
            projectUID: this.project_uid,
            labelUID: this.uid,
        });
    }

    public get project_uid() {
        return this.getValue("project_uid");
    }
    public set project_uid(value) {
        this.update({ project_uid: value });
    }

    public get global_label_uid() {
        return this.getValue("global_label_uid");
    }

    public get global_display() {
        return this.getValue("global_display");
    }
    public set global_display(value) {
        this.update({ global_display: value });
    }

    public get name() {
        return this.getValue("name");
    }
    public set name(value) {
        this.update({ name: value });
    }

    public get color() {
        return this.getValue("color");
    }
    public set color(value) {
        this.update({ color: value });
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
}

registerModel(ProjectLabel);

export type TModel = ProjectLabel;
export const Model = ProjectLabel;
