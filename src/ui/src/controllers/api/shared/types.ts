import { TCreatedAtModelName } from "@/core/models/ModelRegistry";

export type TActivityType = "user" | "project" | "project_column" | "card" | "project_wiki";

export interface IBaseGetListForm<TModelName extends TCreatedAtModelName> {
    listType: TModelName;
}

interface IBaseGetActivitiesForm<TActivity extends TActivityType> extends IBaseGetListForm<"ActivityModel"> {
    listType: "ActivityModel";
    type: TActivity;
    assignee_uid?: string;
}

interface IGetUserActivitiesForm extends IBaseGetActivitiesForm<"user"> {
    user_uid: string;
}

interface IGerProjectActivitiesForm extends IBaseGetActivitiesForm<"project"> {
    project_uid: string;
}

interface IGetProjectColumnActivitiesForm extends IBaseGetActivitiesForm<"project_column"> {
    project_uid: string;
    project_column_uid: string;
}

interface IGetCardActivitiesForm extends IBaseGetActivitiesForm<"card"> {
    project_uid: string;
    card_uid: string;
}

interface IGetProjectWikiActivitiesForm extends IBaseGetActivitiesForm<"project_wiki"> {
    project_uid: string;
    wiki_uid: string;
}

export type TGetActivitiesForm =
    | IGetUserActivitiesForm
    | IGerProjectActivitiesForm
    | IGetProjectColumnActivitiesForm
    | IGetCardActivitiesForm
    | IGetProjectWikiActivitiesForm;

export type TGetListForm<TModelName extends TCreatedAtModelName> = TModelName extends "ActivityModel"
    ? IBaseGetActivitiesForm<TActivityType>
    : IBaseGetListForm<TModelName>;
