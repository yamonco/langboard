import { BaseModel, IBaseModel } from "@/core/models/Base";
import { registerModel } from "@/core/models/ModelRegistry";
import * as GlobalRelationshipType from "@/core/models/GlobalRelationshipType";

export type TRelationship = "parents" | "children";

export interface Interface extends IBaseModel {
    relationship_type_uid: string;
    parent_card_uid: string;
    child_card_uid: string;
    machine_semantic?: "contains" | "blocks" | "references" | null;
    affects_readiness?: boolean;
}

class ProjectCardRelationship extends BaseModel<Interface> {
    public static get MODEL_NAME() {
        return "ProjectCardRelationship" as const;
    }

    public get relationship_type_uid() {
        return this.getValue("relationship_type_uid");
    }

    public get machine_semantic() {
        return this.getValue("machine_semantic");
    }

    public get affects_readiness() {
        return this.getValue("affects_readiness");
    }
    public set relationship_type_uid(value) {
        this.update({ relationship_type_uid: value });
    }

    public get parent_card_uid() {
        return this.getValue("parent_card_uid");
    }
    public set parent_card_uid(value) {
        this.update({ parent_card_uid: value });
    }

    public get child_card_uid() {
        return this.getValue("child_card_uid");
    }
    public set child_card_uid(value) {
        this.update({ child_card_uid: value });
    }

    public get relationship_type(): GlobalRelationshipType.TModel {
        return GlobalRelationshipType.Model.getModel(this.relationship_type_uid)!;
    }
}

registerModel(ProjectCardRelationship);

export type TModel = ProjectCardRelationship;
export const Model = ProjectCardRelationship;
