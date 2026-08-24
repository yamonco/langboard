import { TBotRelatedTargetTable } from "@/core/models/types/bot.related.type";

export type TBotScheduleRelatedParams = {
    target_table: TBotRelatedTargetTable;
    bot_uid: string;
};

export type TBotScheduleMutationParams = TBotScheduleRelatedParams & {
    project_uid: string;
};
