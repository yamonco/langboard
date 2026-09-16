import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { BotModel } from "@/core/models";
import { EBotPlatform, EBotPlatformRunningType } from "@langboard/core/ai";
import { Utils } from "@langboard/core/utils";

export interface IUpdateBotForm {
    bot_name?: string;
    bot_uname?: string;
    platform?: EBotPlatform;
    platform_running_type?: EBotPlatformRunningType;
    api_url?: string;
    api_key?: string;
    ip_whitelist?: string[];
    value?: string;
    avatar?: File;
    delete_avatar?: bool;
}

export interface IUpdateBotResponse {
    name?: string;
    bot_uname?: string;
    avatar?: string;
    deleted_avatar?: bool;
    platform?: string;
    platform_running_type?: string;
    api_url?: string;
    api_key?: string;
    value?: string;
}

const useUpdateBot = (bot: BotModel.TModel, options?: TMutationOptions<IUpdateBotForm, IUpdateBotResponse>) => {
    const { mutate } = useQueryMutation();

    const updateBot = async (params: IUpdateBotForm) => {
        const url = Utils.String.format(Routing.API.SETTINGS.BOTS.UPDATE, { bot_uid: bot.uid });
        const formData = new FormData();
        Object.entries(params).forEach(([key, value]) => {
            if (Utils.Type.isNullOrUndefined(value)) {
                return;
            }

            const isAvatar = (targetKey: string, _: unknown): _ is File => targetKey === "avatar";

            if (isAvatar(key, value)) {
                if (!value) {
                    return;
                }

                formData.append(key, value, value.name);
            } else {
                formData.append(key, value.toString());
            }
        });

        const res = await api.put<IUpdateBotResponse>(url, formData, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const data = res.data;
        Object.entries(data).forEach(([key, value]) => {
            if (key === "deleted_avatar") {
                if (value) {
                    bot.avatar = undefined;
                }
                return;
            }

            if (key === "avatar" && Utils.Type.isString(value)) {
                value = Utils.String.convertServerFileURL(value);
            }

            if (key === "platform" && Utils.Type.isString(value)) {
                value = Utils.String.convertSafeEnum(EBotPlatform, value);
            }

            if (key === "platform_running_type" && Utils.Type.isString(value)) {
                value = Utils.String.convertSafeEnum(EBotPlatformRunningType, value);
            }

            bot[key] = value as never;
        });

        return data;
    };

    const result = mutate(["update-bot"], updateBot, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUpdateBot;
