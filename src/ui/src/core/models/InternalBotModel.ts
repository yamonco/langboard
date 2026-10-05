import useInternalBotSettingDefaultChangedHandlers from "@/controllers/socket/settings/internalBots/useInternalBotSettingDefaultChangedHandlers";
import { BaseModel } from "@/core/models/Base";
import { EBotPlatform, EBotPlatformRunningType } from "@langboard/core/ai";
import { registerModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { IBaseBotModel } from "@/core/models/types/bot.related.type";

export enum EInternalBotType {
    ProjectChat = "project_chat",
    EditorChat = "editor_chat",
    EditorCopilot = "editor_copilot",
    DocumentVision = "document_vision",
}

export interface Interface extends IBaseBotModel {
    bot_type: EInternalBotType;
    display_name: string;
    api_url: string;
    api_key: string;
    value: string;
    is_default: bool;
    avatar?: string;
}

class InternalBotModel extends BaseModel<Interface> {
    public static get MODEL_NAME() {
        return "InternalBotModel" as const;
    }

    constructor(model: Record<string, unknown>) {
        super(model);

        this.subscribeSocketEvents([useInternalBotSettingDefaultChangedHandlers], {
            internalBot: this,
        });
    }

    public static convertModel(model: Interface): Interface {
        if (model.avatar) {
            model.avatar = Utils.String.convertServerFileURL(model.avatar);
        }

        if (Utils.Type.isString(model.bot_type)) {
            model.bot_type = Utils.String.convertSafeEnum(EInternalBotType, model.bot_type);
        }

        if (Utils.Type.isString(model.platform)) {
            model.platform = Utils.String.convertSafeEnum(EBotPlatform, model.platform);
        }

        if (Utils.Type.isString(model.platform_running_type)) {
            model.platform_running_type = Utils.String.convertSafeEnum(EBotPlatformRunningType, model.platform_running_type);
        }

        return model;
    }

    public get bot_type() {
        return this.getValue("bot_type");
    }
    public set bot_type(value) {
        this.update({ bot_type: value });
    }

    public get display_name() {
        return this.getValue("display_name");
    }
    public set display_name(value) {
        this.update({ display_name: value });
    }

    public get platform() {
        return this.getValue("platform");
    }
    public set platform(value) {
        this.update({ platform: value });
    }

    public get platform_running_type() {
        return this.getValue("platform_running_type");
    }
    public set platform_running_type(value) {
        this.update({ platform_running_type: value });
    }

    public get api_url() {
        return this.getValue("api_url");
    }
    public set api_url(value) {
        this.update({ api_url: value });
    }

    public get api_key() {
        return this.getValue("api_key");
    }
    public set api_key(value) {
        this.update({ api_key: value });
    }

    public get value() {
        return this.getValue("value");
    }
    public set value(value) {
        this.update({ value: value });
    }

    public get is_default() {
        return this.getValue("is_default");
    }
    public set is_default(value) {
        this.update({ is_default: value });
    }

    public get avatar() {
        return this.getValue("avatar");
    }
    public set avatar(value) {
        this.update({ avatar: value });
    }
}

registerModel(InternalBotModel);

export const Model = InternalBotModel;
export type TModel = InternalBotModel;
