import { TBotScheduleMutationParams } from "@/controllers/api/shared/botSchedules/types";
import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { BaseBotScheduleModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import { TBotRelatedTargetModel } from "@/core/models/types/bot.related.type";

export type TRescheduleBotCronParams = TBotScheduleMutationParams & {
    schedule_uid: string;
};

export interface IRescheduleBotCronForm {
    scope?: TBotRelatedTargetModel;
    interval?: string;
    running_type?: BaseBotScheduleModel.ERunningType;
    start_at?: Date;
    end_at?: Date;
}

const useRescheduleBotCron = (params: TRescheduleBotCronParams, options?: TMutationOptions<IRescheduleBotCronForm>) => {
    const { mutate } = useQueryMutation();

    let url;
    switch (params.target_table) {
        case "project":
        case "project_column":
        case "card":
            url = Utils.String.format(Routing.API.BOT.SCHEDULE.PROJECT_RESCHEDULE, {
                project_uid: params.project_uid,
                bot_uid: params.bot_uid,
                schedule_uid: params.schedule_uid,
            });
            break;
        default:
            throw new Error("Invalid target_table");
    }

    const rescheduleBotCron = async (form: IRescheduleBotCronForm) => {
        const res = await api.put(
            url,
            {
                interval_str: form.interval,
                target_table: form.scope ? params.target_table : undefined,
                target_uid: form.scope?.uid,
                project_uid: form.scope ? ("project_uid" in form.scope ? form.scope.project_uid : form.scope.uid) : undefined,
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

    const result = mutate(["reschedule-bot-cron"], rescheduleBotCron, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useRescheduleBotCron;
