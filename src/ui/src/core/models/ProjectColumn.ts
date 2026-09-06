import useBoardColumnDeletedHandlers from "@/controllers/socket/board/column/useBoardColumnDeletedHandlers";
import useBoardColumnDescriptionChangedHandlers from "@/controllers/socket/board/column/useBoardColumnDescriptionChangedHandlers";
import useBoardCardCreatedHandlers from "@/controllers/socket/board/useBoardCardCreatedHandlers";
import { BaseModel, IBaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";

export interface Interface extends IBaseModel {
    project_uid: string;
    name: string;
    description?: string;
    order: number;
    is_archive: bool;
}

export interface IStore extends Interface {
    count: number;
}

class ProjectColumn extends BaseModel<IStore> {
    public static get MODEL_NAME() {
        return "ProjectColumn" as const;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        this.subscribeSocketEvents([useBoardCardCreatedHandlers, useBoardColumnDeletedHandlers, useBoardColumnDescriptionChangedHandlers], {
            projectUID: this.project_uid,
            columnUID: this.uid,
            column: this,
        });
    }

    public get project_uid() {
        return this.getValue("project_uid");
    }
    public set project_uid(value) {
        this.update({ project_uid: value });
    }

    public get name() {
        return this.getValue("name");
    }
    public set name(value) {
        this.update({ name: value });
    }

    public get order() {
        return this.getValue("order");
    }

    public get description() {
        return this.getValue("description") ?? "";
    }
    public set description(value) {
        this.update({ description: value });
    }
    public set order(value) {
        this.update({ order: value });
    }

    public get count() {
        return this.getValue("count");
    }
    public set count(value) {
        this.update({ count: value });
    }

    public get is_archive() {
        return this.getValue("is_archive");
    }
    public set is_archive(value) {
        this.update({ is_archive: value });
    }
}

registerModel(ProjectColumn);

export type TModel = ProjectColumn;
export const Model = ProjectColumn;
