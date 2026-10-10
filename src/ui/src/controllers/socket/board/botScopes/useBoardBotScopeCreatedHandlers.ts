import { SocketEvents } from "@langboard/core/constants";
import useSocketHandler, { IBaseUseSocketHandlersProps } from "@/core/helpers/SocketHandler";
import { TBotRelatedTargetTable } from "@/core/models/types/bot.related.type";
import { ProjectBotScope, ProjectColumnBotScope, ProjectCardBotScope } from "@/core/models";
import { ESocketTopic } from "@langboard/core/enums";
import { BOT_SCOPES } from "@/core/constants/BotRelatedConstants";

export interface IBoardBotScopeCreatedRawResponse {
    scope_table: TBotRelatedTargetTable;
    bot_scope: ProjectBotScope.Interface | ProjectColumnBotScope.Interface | ProjectCardBotScope.Interface;
}

export interface IUseBoardBotScopeCreatedHandlersProps extends IBaseUseSocketHandlersProps<{}> {
    projectUID: string;
}

const useBoardBotScopeCreatedHandlers = ({ callback, projectUID }: IUseBoardBotScopeCreatedHandlersProps) => {
    return useSocketHandler<{}, IBoardBotScopeCreatedRawResponse>({
        topic: ESocketTopic.BoardSettings,
        topicId: projectUID,
        eventKey: `board-bot-scope-created-${projectUID}`,
        onProps: {
            name: SocketEvents.SERVER.BOARD.BOT.SCOPE.CREATED,
            callback,
            responseConverter: (data) => {
                const targetModel = BOT_SCOPES[data.scope_table];
                if (targetModel) {
                    targetModel.Model.fromOne(data.bot_scope, true);
                }

                return {};
            },
        },
    });
};

export default useBoardBotScopeCreatedHandlers;
