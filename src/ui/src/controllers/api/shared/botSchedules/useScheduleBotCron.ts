import { TBotScheduleMutationParams } from "@/controllers/api/shared/botSchedules/types";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { BaseBotScheduleModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { TBotRelatedTargetModel } from "@/core/models/types/bot.related.type";

export interface IScheduleBotCronForm {
    scope: TBotRelatedTargetModel;
    interval: string;
    running_type?: BaseBotScheduleModel.ERunningType;
    start_at?: Date;
    end_at?: Date;
}

const useScheduleBotCron = (params: TBotScheduleMutationParams, options?: TMutationOptions<IScheduleBotCronForm>) => {
    const { mutate } = useQueryMutation();

    switch (params.target_table) {
        case "project":
        case "project_column":
        case "card":
            break;
        default:
            throw new Error("Invalid target_table");
    }

    const scheduleBotCron = async (form: IScheduleBotCronForm) => {
        const url = Utils.String.format(Routing.API.BOT.SCHEDULE.PROJECT_SCHEDULE, {
            project_uid: params.project_uid,
            bot_uid: params.bot_uid,
        });
        const res = await api.post(
            url,
            {
                interval_str: form.interval,
                target_table: params.target_table,
                target_uid: form.scope.uid,
                running_type: form.running_type,
                start_at: form.start_at,
                end_at: form.end_at,
                timezone: new Date().getTimezoneOffset() / -60,
            },
            {
                env: {
                    interceptToast: options?.interceptToast,
                } as never,
            }
        );

        return res.data;
    };

    const result = mutate(["schedule-bot-cron"], scheduleBotCron, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useScheduleBotCron;
