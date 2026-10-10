import { TGetListForm } from "@/controllers/api/shared/types";
import { Routing } from "@langboard/core/constants";
import { ActivityModel, ApiKeySettingModel, User } from "@/core/models";
import { Utils } from "@langboard/core/utils";

export const getListRequestData = (form: TGetListForm) => {
    let model;
    let url;
    switch (form.listType) {
        case "ActivityModel":
            model = ActivityModel.Model;
            switch (form.type) {
                case "user":
                    url = Routing.API.ACTIVITIY.USER;
                    break;
                case "project":
                    url = Utils.String.format(Routing.API.ACTIVITIY.PROJECT, { uid: form.project_uid });
                    break;
                case "project_column":
                    url = Utils.String.format(Routing.API.ACTIVITIY.PROJECT_COLUMN, {
                        uid: form.project_uid,
                        project_column_uid: form.project_column_uid,
                    });
                    break;
                case "card":
                    url = Utils.String.format(Routing.API.ACTIVITIY.CARD, { uid: form.project_uid, card_uid: form.card_uid });
                    break;
                case "project_wiki":
                    url = Utils.String.format(Routing.API.ACTIVITIY.PROJECT_WIKI, { uid: form.project_uid, wiki_uid: form.wiki_uid });
                    break;
                default:
                    throw new Error("Invalid activity type");
            }
            break;
        case "User":
            model = User.Model;
            url = Routing.API.SETTINGS.USERS.GET_LIST;
            break;
        case "ApiKeySettingModel":
            model = ApiKeySettingModel.Model;
            url = Routing.API.SETTINGS.API_KEYS.GET_LIST;
            break;
        default:
            throw new Error("Invalid list type");
    }

    return [model, url] as const;
};
