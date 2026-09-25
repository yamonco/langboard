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

const useUpdateBot = (bot: BotModel.TModel, options?: TMutationOptions<IUpdateBotForm>) => {
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

        const res = await api.put(url, formData, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        if (Utils.Type.isObject(res.data)) {
            Object.entries(res.data).forEach(([key, value]) => {
                if (key === "platform" && Utils.Type.isString(value)) {
                    value = EBotPlatform[new Utils.String.Case(value).toPascal() as keyof typeof EBotPlatform];
                }

                if (key === "platform_running_type" && Utils.Type.isString(value)) {
                    value = EBotPlatformRunningType[new Utils.String.Case(value).toPascal() as keyof typeof EBotPlatformRunningType];
                }

                bot[key] = value as never;
            });
        }

        return res.data;
    };

    const result = mutate(["update-bot"], updateBot, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUpdateBot;
