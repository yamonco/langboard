import { TBotScheduleRelatedParams } from "@/controllers/api/shared/botSchedules/types";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { Utils } from "@langboard/core/utils";
import { BOT_SCHEDULES } from "@/core/constants/BotRelatedConstants";

export type TUnscheduleBotCronParams = TBotScheduleRelatedParams & {
    project_uid: string;
    schedule_uid: string;
    target_uid: string;
};

const useUnscheduleBotCron = (params: TUnscheduleBotCronParams, options?: TMutationOptions) => {
    const { mutate } = useQueryMutation();

    const unscheduleBotCron = async () => {
        let url;
        switch (params.target_table) {
            case "project":
            case "project_column":
            case "card":
                url = Utils.String.format(Routing.API.BOT.SCHEDULE.PROJECT_UNSCHEDULE, {
                    project_uid: params.project_uid,
                    bot_uid: params.bot_uid,
                    schedule_uid: params.schedule_uid,
                });
                break;
            default:
                throw new Error("Invalid target_table");
        }

        const res = await api.delete(url, {
            data: {
                target_table: params.target_table,
                target_uid: params.target_uid,
                project_uid: params.project_uid,
            },
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        const targetModel = BOT_SCHEDULES[params.target_table];
        if (targetModel) {
            targetModel.Model.deleteModel(params.schedule_uid);
        }

        return res.data;
    };

    const result = mutate(["unschedule-bot-cron"], unscheduleBotCron, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useUnscheduleBotCron;
