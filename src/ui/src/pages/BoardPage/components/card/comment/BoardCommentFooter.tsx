import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Separator from "@/components/base/Separator";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import { isEmptyEditorContent, sanitizeEditorContent, sanitizeEditorValue } from "@/components/Editor/utils";
import useDeleteCardComment from "@/controllers/api/card/comment/useDeleteCardComment";
import useUpdateCardComment from "@/controllers/api/card/comment/useUpdateCardComment";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { IEditorContent } from "@/core/models/Base";
import { isModel, ModelRegistry } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { getEditorStore } from "@/core/stores/EditorStore";
import BoardCommentReaction from "@/pages/BoardPage/components/card/comment/BoardCommentReaction";
import { IBoardCommentContextParams } from "@/pages/BoardPage/components/card/comment/types";
import { useState } from "react";
import { useTranslation } from "react-i18next";

function BoardCommentFooter(): React.JSX.Element {
    const { params } = ModelRegistry.ProjectCardComment.useContext<IBoardCommentContextParams>();
    const { isCurrentEditor } = params;

    return (
        <Flex items="center" gap="2">
            {isCurrentEditor ? <BoardCommentFooterEditButtons /> : <BoardCommentFooterActions />}
        </Flex>
    );
}

function BoardCommentFooterEditButtons() {
    const { projectUID, card } = useBoardCard();
    const [t] = useTranslation();
    const { model: comment, params } = ModelRegistry.ProjectCardComment.useContext<IBoardCommentContextParams>();
    const { valueRef } = params;
    const [isValidating, setIsValidating] = useState(false);
    const setValue = (value: IEditorContent) => {
        valueRef.current = value;
    };
    const { mutate: updateCommentMutate } = useUpdateCardComment();

    const cancelEditing = () => {
        setValue(comment.content);
        getEditorStore().setCurrentEditor(null);
    };

    const saveComment = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const content = sanitizeEditorValue(valueRef.current);

        if (isEmptyEditorContent(content.content)) {
            Toast.Add.error(t("card.errors.Comment content cannot be empty."));
            setIsValidating(false);
            return;
        }

        if (sanitizeEditorContent(comment.content.content) === content.content) {
            setIsValidating(false);
            return;
        }

        updateCommentMutate(
            {
                project_uid: projectUID,
                card_uid: card.uid,
                comment_uid: comment.uid,
                content,
            },
            {
                onSuccess: () => {
                    comment.content = content;
                    Toast.Add.success(t("successes.Comment updated successfully."));
                    cancelEditing();
                },
                onError: (error) => {
                    const { handle } = setupApiErrorHandler({});

                    handle(error);
                    cancelEditing();
                },
                onSettled: () => {
                    setIsValidating(false);
                },
            }
        );
    };

    return (
        <>
            <Button variant="secondary" onClick={cancelEditing} disabled={isValidating}>
                {t("common.Cancel")}
            </Button>
            <SubmitButton type="button" onClick={saveComment} isValidating={isValidating}>
                {t("common.Save")}
            </SubmitButton>
        </>
    );
}

function BoardCommentFooterActions() {
    const { projectUID, card, currentUser, hasRoleAction, replyRef } = useBoardCard();
    const [t] = useTranslation();
    const { model: comment, params } = ModelRegistry.ProjectCardComment.useContext<IBoardCommentContextParams>();
    const { author, deletedComment, editorName, valueRef } = params;
    const isAdmin = currentUser.useField("is_admin");
    const [isValidating, setIsValidating] = useState(false);
    const canEdit = currentUser.uid === author.uid || isAdmin;
    const canReply = !isModel(author, "User") || author.isValidUser();
    const { mutateAsync: deleteCommentMutateAsync } = useDeleteCardComment({ interceptToast: true });
    const startEditing = () => {
        valueRef.current = comment.content;
        getEditorStore().setCurrentEditor(editorName);
    };

    const deleteComment = () => {
        if (isValidating) {
            return;
        }

        setIsValidating(true);

        const promise = deleteCommentMutateAsync({
            project_uid: projectUID,
            card_uid: card.uid,
            comment_uid: comment.uid,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Deleting..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                deletedComment(comment.uid);
                return t("successes.Comment deleted successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    return (
        <>
            <BoardCommentReaction comment={comment} />
            {hasRoleAction(ProjectRole.EAction.Read) && currentUser.uid !== author.uid && currentUser.isValidUser() && canReply && (
                <>
                    <Separator orientation="vertical" className="h-1/2" />
                    <Button
                        variant="link"
                        size="sm"
                        data-reply-component
                        className="h-5 p-0 text-accent-foreground/50"
                        onClick={() => replyRef.current?.(author)}
                    >
                        {t("card.Reply")}
                    </Button>
                </>
            )}
            {canEdit && (
                <>
                    <Separator orientation="vertical" className="h-1/2" />
                    <Button variant="link" size="sm" className="h-5 p-0 text-accent-foreground/50" onClick={startEditing} disabled={isValidating}>
                        {t("common.Edit")}
                    </Button>
                    <Separator orientation="vertical" className="h-1/2" />
                    <Button variant="link" size="sm" className="h-5 p-0 text-accent-foreground/50" onClick={deleteComment} disabled={isValidating}>
                        {t("common.Delete")}
                    </Button>
                </>
            )}
        </>
    );
}

export default BoardCommentFooter;
