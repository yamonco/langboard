import ReactionCounter, { TReactionEmoji } from "@/components/ReactionCounter";
import { IReactionActor, resolveReactionActorNames } from "@/components/ReactionCounter/reactionActorNames";
import useReactCardComment from "@/controllers/api/card/comment/useReactCardComment";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { BotModel, ProjectCardComment } from "@/core/models";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBoardCommentReactionProps {
    comment: ProjectCardComment.TModel;
}

const BoardCommentReaction = ({ comment }: IBoardCommentReactionProps): React.JSX.Element => {
    const { projectUID, card, currentUser } = useBoardCard();
    const [t] = useTranslation();
    const reactions = comment.useField("reactions");
    const projectMembers = card.useForeignFieldArray("project_members");
    const bots = BotModel.Model.useModels(() => true);
    const { mutate: reactCardCommentMutate } = useReactCardComment();
    const [isValidating, setIsValidating] = useState(false);
    const actors = useMemo<IReactionActor[]>(
        () => [
            ...projectMembers.map((user) => ({
                uid: user.uid,
                name: `${user.firstname} ${user.lastname}`.trim() || user.username || t("common.Unknown User"),
            })),
            ...bots.map((bot) => ({ uid: bot.uid, name: `${bot.name} (${t("reaction.Bot")})` })),
        ],
        [projectMembers, bots, t]
    );
    const reactionActorNames = Object.fromEntries(
        Object.entries(reactions).map(([reaction, reactionUIDs]) => [
            reaction,
            resolveReactionActorNames(reactionUIDs ?? [], actors, t("common.Unknown User")),
        ])
    );

    const submitToggleReaction = (reaction: TReactionEmoji) => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        reactCardCommentMutate(
            {
                project_uid: projectUID,
                card_uid: card.uid,
                comment_uid: comment.uid,
                reaction,
            },
            {
                onError: (error) => {
                    const { handle } = setupApiErrorHandler({});

                    handle(error);
                },
                onSettled: () => {
                    setIsValidating(false);
                },
            }
        );
    };

    return (
        <ReactionCounter
            reactions={reactions}
            reactionActorNames={reactionActorNames}
            isActiveReaction={(_, data) => {
                return data.includes(currentUser.uid);
            }}
            toggleCallback={submitToggleReaction}
            disabled={isValidating}
        />
    );
};

export default BoardCommentReaction;
