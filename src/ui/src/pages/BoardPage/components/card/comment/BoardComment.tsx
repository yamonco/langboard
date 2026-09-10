import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";
import DateDistance from "@/components/DateDistance";
import { TEditor } from "@/components/Editor/editor-kit";
import { PlateEditor } from "@/components/Editor/plate-editor";
import UserAvatar from "@/components/UserAvatar";
import UserAvatarDefaultList from "@/components/UserAvatarDefaultList";
import UserLikeComponent from "@/components/UserLikeComponent";
import { BotModel, ProjectCard, ProjectCardComment, User } from "@/core/models";
import { IEditorContent } from "@/core/models/Base";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { useIsCurrentEditor } from "@/core/stores/EditorStore";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCommentFooter from "@/pages/BoardPage/components/card/comment/BoardCommentFooter";
import { IBoardCommentContextParams } from "@/pages/BoardPage/components/card/comment/types";
import { EEditorType } from "@langboard/core/constants";
import { memo, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { resolveCardCommentAnchorElement } from "@/pages/BoardPage/components/card/comment/commentAnchor";

export function SkeletonBoardComment({ ref }: { ref?: React.Ref<HTMLDivElement> }): React.JSX.Element {
    return (
        <Box mt="4" display="grid" gap="2" className="grid-cols-[theme(spacing.8),1fr]" ref={ref}>
            <Skeleton size="8" rounded="full" />
            <Flex direction="col" gap="1">
                <Flex gap="1" items="center">
                    <Skeleton h="5" w="24" />
                    <Skeleton h="4" w="36" />
                </Flex>
                <Skeleton h="12" rounded="lg" className="w-1/2 rounded-ss-none" />
            </Flex>
        </Box>
    );
}

export interface IBoardCommentProps {
    comment: ProjectCardComment.TModel;
    deletedComment: (commentUID: string) => void;
}

const BoardComment = memo(({ comment, deletedComment }: IBoardCommentProps): React.JSX.Element => {
    const { projectUID, card, currentUser } = useBoardCard();
    const editorName = `${card.uid}-comment-${comment.uid}`;
    const isCurrentEditor = useIsCurrentEditor(editorName);
    const projectMembers = card.useForeignFieldArray("project_members");
    const editorRef = useRef<TEditor>(null);
    const bots = BotModel.Model.useModels(() => true);
    const mentionables = useMemo(() => [...projectMembers, ...bots], [projectMembers, bots]);
    const cards = ProjectCard.Model.useModels((model) => model.uid !== card.uid && model.project_uid === projectUID, [projectUID, card]);
    const content = comment.useField("content");
    const anchor = comment.useField("anchor");
    const commentUser = comment.useForeignFieldOne("user");
    const commentBot = comment.useForeignFieldOne("bot");
    const commentAuthor = commentUser || commentBot;
    const valueRef = useRef<IEditorContent>(content);
    const setValue = (value: IEditorContent) => {
        valueRef.current = value;
    };
    const editorValue = isCurrentEditor ? valueRef.current : content;

    return (
        <ModelRegistry.ProjectCardComment.Provider
            model={comment}
            params={{ author: commentAuthor, deletedComment, valueRef, editorName, isCurrentEditor, editorRef }}
        >
            <Box data-card-comment-uid={comment.uid} display="grid" gap="2" className="grid-cols-[theme(spacing.8),minmax(0,1fr)]">
                <Box>
                    <BoardCommentUserAvatar projectUID={projectUID} cardUID={card.uid} />
                </Box>
                <Flex direction="col" gap="2" className="max-w-full">
                    <BoardCommentHeader />
                    {anchor && (
                        <button
                            type="button"
                            className={cn(
                                "max-w-full truncate rounded-md border-l-2 border-brand bg-brand/10 px-2 py-1 text-left text-xs",
                                "text-muted-foreground hover:bg-brand/15"
                            )}
                            title={anchor.exact}
                            onClick={() => {
                                const description = document.querySelector<HTMLElement>("[data-card-description]");
                                if (!description) {
                                    return;
                                }
                                resolveCardCommentAnchorElement(description, anchor)?.scrollIntoView({
                                    behavior: "smooth",
                                    block: "center",
                                });
                            }}
                        >
                            “{anchor.exact}”
                        </button>
                    )}
                    <Flex
                        px="3"
                        py="1.5"
                        rounded="lg"
                        className={cn(
                            "min-w-0 rounded-ss-none bg-accent/70",
                            isCurrentEditor ? "w-full max-w-full overflow-hidden border bg-transparent p-0" : "w-fit max-w-full"
                        )}
                    >
                        <PlateEditor
                            key={`board-comment-editor-${comment.uid}-${isCurrentEditor ? "edit" : "view"}`}
                            value={editorValue}
                            currentUser={currentUser}
                            mentionables={mentionables}
                            linkables={cards}
                            className={
                                isCurrentEditor ? "h-full max-h-[min(70vh,300px)] min-h-[min(70vh,300px)] min-w-0 overflow-y-auto px-4 py-3" : ""
                            }
                            focusOnReady={isCurrentEditor}
                            readOnly={!isCurrentEditor}
                            editorType={EEditorType.CardComment}
                            form={{
                                project_uid: projectUID,
                                card_uid: card.uid,
                                comment_uid: comment.uid,
                            }}
                            setValue={setValue}
                            editorRef={editorRef}
                        />
                    </Flex>
                    <BoardCommentFooter />
                </Flex>
            </Box>
        </ModelRegistry.ProjectCardComment.Provider>
    );
});

function BoardCommentUserAvatar({ projectUID, cardUID }: { projectUID: string; cardUID: string }): React.JSX.Element {
    const { params } = ModelRegistry.ProjectCardComment.useContext<IBoardCommentContextParams>();
    const { author } = params;

    return (
        <UserAvatar.Root avatarSize="sm" userOrBot={author}>
            <UserAvatarDefaultList
                userOrBot={author}
                scope={{
                    projectUID,
                    cardUID,
                }}
            />
        </UserAvatar.Root>
    );
}

function BoardCommentHeader(): React.JSX.Element {
    const [t] = useTranslation();
    const { model: comment, params } = ModelRegistry.ProjectCardComment.useContext<IBoardCommentContextParams>();
    const { author } = params;
    const commentedAt = comment.useField("updated_at");
    const isEdited = comment.useField("is_edited");

    return (
        <Flex gap="2" items="center">
            <span className="text-sm font-bold">
                <UserLikeComponent
                    userOrBot={author}
                    userComp={BoardCommentUserHeader}
                    botComp={BoardCommentBotHeader}
                    customNullReturn={<Skeleton className="h-4 w-24" />}
                />
            </span>
            <span className="text-xs text-accent-foreground/50">
                <DateDistance date={commentedAt} />
                {isEdited && ` (${t("card.edited")})`}
            </span>
        </Flex>
    );
}

function BoardCommentUserHeader({ user }: { user: User.TModel }): React.JSX.Element {
    const [t] = useTranslation();
    const type = user.useField("type");
    const firstname = user.useField("firstname");
    const lastname = user.useField("lastname");

    if (user.isDeletedUser(type)) {
        return <>{t("common.Unknown User")}</>;
    }

    return (
        <>
            {firstname} {lastname}
        </>
    );
}

function BoardCommentBotHeader({ bot }: { bot: BotModel.TModel }): React.JSX.Element {
    const name = bot.useField("name");

    return <>{name}</>;
}

export default BoardComment;
