import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Drawer from "@/components/base/Drawer";
import Flex from "@/components/base/Flex";
import Form from "@/components/base/Form";
import Skeleton from "@/components/base/Skeleton";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import UserAvatar from "@/components/UserAvatar";
import { useTranslation } from "react-i18next";
import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PlateEditor } from "@/components/Editor/plate-editor";
import { isEmptyEditorContent, sanitizeEditorContent, sanitizeEditorValue } from "@/components/Editor/utils";
import { IEditorContent } from "@/core/models/Base";
import { useBoardCard, useBoardCardPanel } from "@/core/providers/BoardCardProvider";
import useAddCardComment from "@/controllers/api/card/comment/useAddCardComment";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useToggleEditingByClickOutside from "@/core/hooks/useToggleEditingByClickOutside";
import { isModel, TUserLikeModel } from "@/core/models/ModelRegistry";
import { BotModel, ProjectCard } from "@/core/models";
import { getEditorStore, useIsCurrentEditor } from "@/core/stores/EditorStore";
import { getCardCommentDraftStore } from "@/core/stores/CardCommentDraftStore";
import { TEditor } from "@/components/Editor/editor-kit";
import { EEditorType } from "@langboard/core/constants";
import { getMentionOnSelectItem } from "@platejs/mention";

export function SkeletonBoardCommentForm() {
    return (
        <Box
            position="sticky"
            bottom={{ initial: "0", sm: "-2" }}
            className="-ml-[calc(theme(spacing.4))] w-[calc(100%_+_theme(spacing.8))] bg-background"
        >
            <Flex items="center" gap="4" p="2" className="rounded-b-lg border-t">
                <Skeleton size="8" rounded="full" className="overflow-hidden" />
                <Box w="full" cursor="text" py="1">
                    <Skeleton h="6" className="w-1/3" />
                </Box>
            </Flex>
        </Box>
    );
}
export interface IBoardCommentFormProps {
    variant?: "mobile" | "panel";
}

const insertMention = getMentionOnSelectItem();

const BoardCommentForm = memo(({ variant = "mobile" }: IBoardCommentFormProps): React.JSX.Element | null => {
    const { projectUID, card, currentUser, replyRef } = useBoardCard();
    const { isCommentPanelOpen, setIsCommentPanelOpen, commentLayoutMode } = useBoardCardPanel();
    const [t] = useTranslation();
    const isPanelLayout = commentLayoutMode === "panel";
    const isVisible = isCommentPanelOpen && (variant === "mobile" ? !isPanelLayout : isPanelLayout);
    const projectMembers = card.useForeignFieldArray("project_members");
    const bots = BotModel.Model.useModels(() => true);
    const mentionables = useMemo(() => [...projectMembers, ...bots], [projectMembers, bots]);
    const cards = ProjectCard.Model.useModels((model) => model.uid !== card.uid && model.project_uid === projectUID, [projectUID, card]);
    const valueRef = useRef<IEditorContent>({ content: "" });
    const setValue = useCallback((value: IEditorContent) => {
        valueRef.current = value;
    }, []);
    const drawerRef = useRef<HTMLDivElement>(null);
    const editorName = `${card.uid}-comment-form`;
    const isCurrentEditor = useIsCurrentEditor(editorName);
    const [isMobileDrawerOpen, setIsMobileDrawerOpen] = useState(false);
    const [isPanelEditorOpen, setIsPanelEditorOpen] = useState(false);
    const [pendingReplyMention, setPendingReplyMention] = useState<{ uid: string; username: string } | null>(null);
    const [isValidating, setIsValidating] = useState(false);
    const { mutate: addCommentMutate } = useAddCardComment();
    const isClickedRef = useRef(false);
    const isReplyOwner = variant === "panel" ? isPanelLayout : !isPanelLayout;
    const { stopEditing } = useToggleEditingByClickOutside("[data-card-comment-form]", (mode) => {
        if (mode === "view") {
            getEditorStore().setCurrentEditor(null);
        }
    });

    const saveDraftToStorage = useCallback(
        (content: string) => {
            getCardCommentDraftStore().saveDraft(projectUID, card.uid, sanitizeEditorContent(content));
        },
        [projectUID, card]
    );
    const readDraftFromStorage = useCallback((): string => {
        return getCardCommentDraftStore().getDraft(projectUID, card.uid);
    }, [projectUID, card]);
    const clearDraftFromStorage = useCallback(() => {
        getCardCommentDraftStore().clearDraft(projectUID, card.uid);
    }, [projectUID, card]);
    const openEditor = useCallback(() => {
        setValue({ content: readDraftFromStorage() });
        getEditorStore().setCurrentEditor(editorName);
    }, [editorName, readDraftFromStorage, setValue]);
    const clearEditor = useCallback(() => {
        setValue({ content: "" });
        setPendingReplyMention(null);
        clearDraftFromStorage();
    }, [clearDraftFromStorage, setValue]);

    const closePanelEditor = useCallback(() => {
        clearEditor();
        setIsPanelEditorOpen(false);
        getEditorStore().setCurrentEditor(null);
    }, [clearEditor]);
    const handleEditorReady = useCallback(
        (editor: TEditor) => {
            if (!pendingReplyMention) {
                return;
            }

            editor.tf.focus({ edge: "endEditor", retries: 3 });
            insertMention(editor, {
                key: pendingReplyMention.uid,
                text: pendingReplyMention.username,
            });
            editor.tf.insertText(" ");
            setPendingReplyMention(null);
        },
        [pendingReplyMention]
    );

    const closeMobileDrawer = useCallback(() => {
        setIsMobileDrawerOpen(false);
        drawerRef.current?.setAttribute("data-state", "closed");
        setTimeout(() => {
            if (drawerRef.current) {
                drawerRef.current.style.display = "none";
            }
            getEditorStore().setCurrentEditor(null);
        }, 450);
    }, []);
    const cancelMobileEditor = useCallback(() => {
        clearEditor();
        closeMobileDrawer();
    }, [clearEditor, closeMobileDrawer]);

    const onDrawerHandlePointerStart = useCallback(
        (type: "mouse" | "touch") => {
            if (isValidating) {
                return;
            }

            const upEvent = type === "mouse" ? "mouseup" : "touchend";

            const checkIsClick = () => {
                isClickedRef.current = true;
                window.removeEventListener(upEvent, checkIsClick);
            };

            window.addEventListener(upEvent, checkIsClick);

            setTimeout(() => {
                if (isClickedRef.current) {
                    getEditorStore().setCurrentEditor(null);
                    return;
                }

                window.removeEventListener(upEvent, checkIsClick);
            }, 250);
        },
        [isValidating]
    );

    useEffect(() => {
        if (!isReplyOwner) {
            return;
        }

        const handleReply = (target: TUserLikeModel) => {
            if (isValidating) {
                return;
            }

            setIsCommentPanelOpen(true);
            if (variant === "panel") {
                setIsPanelEditorOpen(true);
            } else {
                setIsMobileDrawerOpen(true);
            }

            let username;
            if (isModel(target, "User")) {
                if (!target.isValidUser()) {
                    return;
                }

                username = target.username;
            } else if (isModel(target, "BotModel")) {
                username = target.bot_uname;
            } else {
                return;
            }

            setPendingReplyMention({ uid: target.uid, username });
            if (!isCurrentEditor) {
                openEditor();
            }
        };

        replyRef.current = handleReply;

        return () => {
            if (replyRef.current === handleReply) {
                replyRef.current = () => {};
            }
        };
    }, [isCurrentEditor, isReplyOwner, isValidating, openEditor, setIsCommentPanelOpen, variant]);

    useEffect(() => {
        if (!isCurrentEditor) {
            saveDraftToStorage(valueRef.current.content);
        }
    }, [isCurrentEditor, saveDraftToStorage]);

    useEffect(() => {
        if (!isVisible && isCurrentEditor) {
            getEditorStore().setCurrentEditor(null);
        }
    }, [isCurrentEditor, isVisible]);

    useEffect(() => {
        if (variant === "panel" && !isVisible) {
            setIsPanelEditorOpen(false);
        }
    }, [isVisible, variant]);

    const changeOpenState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        if (!opened) {
            closeMobileDrawer();
            return;
        }

        setIsMobileDrawerOpen(true);
        openEditor();
    };

    const saveComment = () => {
        if (isValidating) {
            return;
        }

        const content = sanitizeEditorValue(valueRef.current);

        if (isEmptyEditorContent(content.content)) {
            Toast.Add.error(t("card.errors.Comment content cannot be empty."));
            return;
        }

        setIsValidating(true);
        addCommentMutate(
            {
                project_uid: projectUID,
                card_uid: card.uid,
                content,
            },
            {
                onSuccess: () => {
                    setValue({ content: "" });
                    clearDraftFromStorage();
                    getEditorStore().setCurrentEditor(null);

                    if (variant === "mobile") {
                        setTimeout(() => {
                            closeMobileDrawer();
                        }, 0);
                    }

                    if (variant === "panel") {
                        setIsPanelEditorOpen(false);
                    }
                },
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

    const clickOutside = (e: React.MouseEvent | CustomEvent) => {
        if (!isCurrentEditor) {
            return;
        }

        stopEditing(e);
    };

    if (!isVisible) {
        return null;
    }

    if (variant === "panel") {
        const isPanelComposerVisible = isPanelEditorOpen || isCurrentEditor;

        return (
            <Form.Root className="w-full">
                <Box data-card-comment-form className="w-full">
                    {!isPanelComposerVisible ? (
                        <Flex
                            items="center"
                            gap="3"
                            rounded="lg"
                            role="button"
                            tabIndex={0}
                            border
                            px="3"
                            py="2.5"
                            className="cursor-text bg-background text-sm text-muted-foreground transition-colors hover:bg-accent/40"
                            onClick={() => {
                                setIsPanelEditorOpen(true);
                                openEditor();
                            }}
                            onKeyDown={(e) => {
                                if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    setIsPanelEditorOpen(true);
                                    openEditor();
                                }
                            }}
                        >
                            <UserAvatar.Root userOrBot={currentUser} avatarSize="sm" />
                            <Box>
                                {t("card.Add a comment as {firstname} {lastname}", {
                                    firstname: currentUser.firstname,
                                    lastname: currentUser.lastname,
                                })}
                            </Box>
                        </Flex>
                    ) : (
                        <Box rounded="lg" border className="overflow-hidden bg-background" data-card-comment-form>
                            <PlateEditor
                                value={valueRef.current}
                                currentUser={currentUser}
                                mentionables={mentionables}
                                linkables={cards}
                                className="max-h-[240px] min-h-[140px] overflow-y-auto px-4 py-3"
                                editorType={EEditorType.CardNewComment}
                                focusOnReady
                                form={{
                                    project_uid: projectUID,
                                    card_uid: card.uid,
                                }}
                                setValue={setValue}
                                onEditorReady={handleEditorReady}
                            />
                            <Flex items="center" gap="2" justify="end" p="2" className="border-t">
                                <Button variant="secondary" onClick={closePanelEditor} disabled={isValidating}>
                                    {t("common.Cancel")}
                                </Button>
                                <SubmitButton type="button" onClick={saveComment} isValidating={isValidating}>
                                    {t("common.Save")}
                                </SubmitButton>
                            </Flex>
                        </Box>
                    )}
                </Box>
            </Form.Root>
        );
    }

    return (
        <Form.Root className="w-full">
            <Drawer.Root
                modal={false}
                handleOnly
                repositionInputs={false}
                open={isMobileDrawerOpen && isCommentPanelOpen && !isPanelLayout}
                onOpenChange={changeOpenState}
            >
                <Flex
                    items="center"
                    gap="4"
                    p="2"
                    role="button"
                    tabIndex={0}
                    className="cursor-text rounded-lg border bg-background shadow-sm"
                    onClick={() => {
                        setIsMobileDrawerOpen(true);
                        openEditor();
                    }}
                    onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setIsMobileDrawerOpen(true);
                            openEditor();
                        }
                    }}
                >
                    <UserAvatar.Root userOrBot={currentUser} avatarSize="sm" />
                    <Box w="full" cursor="text" py="1">
                        {t("card.Add a comment as {firstname} {lastname}", { firstname: currentUser.firstname, lastname: currentUser.lastname })}
                    </Box>
                </Flex>
                <Drawer.Content
                    withGrabber={false}
                    className="rounded-t-none border-none bg-transparent"
                    aria-describedby=""
                    focusGuards={false}
                    onPointerDownOutside={clickOutside}
                    onClick={clickOutside}
                    ref={drawerRef}
                >
                    <Drawer.Title hidden />
                    <Flex
                        direction="col"
                        position="relative"
                        mx="auto"
                        w="full"
                        pt="4"
                        border
                        className="max-w-[100vw] rounded-t-[10px] bg-background sm:max-w-screen-sm lg:max-w-screen-md"
                        data-card-comment-form
                    >
                        <Drawer.Handle
                            className="flex h-2 !w-full cursor-grab justify-center !bg-transparent py-3 text-center"
                            onMouseDown={() => onDrawerHandlePointerStart("mouse")}
                            onTouchStart={() => onDrawerHandlePointerStart("touch")}
                        >
                            <Box display="inline-block" h="2" rounded="full" className="w-[100px] bg-muted" />
                        </Drawer.Handle>
                        <Box position="relative" w="full" className="border-b">
                            <PlateEditor
                                value={valueRef.current}
                                currentUser={currentUser}
                                mentionables={mentionables}
                                linkables={cards}
                                className="h-full max-h-[min(50vh,200px)] min-h-[min(50vh,200px)] overflow-y-auto px-6 py-3"
                                editorType={EEditorType.CardNewComment}
                                focusOnReady
                                form={{
                                    project_uid: projectUID,
                                    card_uid: card.uid,
                                }}
                                setValue={setValue}
                                onEditorReady={handleEditorReady}
                            />
                        </Box>
                        <Flex items="center" gap="2" justify="start" p="1">
                            <Button variant="secondary" onClick={cancelMobileEditor} disabled={isValidating}>
                                {t("common.Cancel")}
                            </Button>
                            <SubmitButton type="button" onClick={saveComment} isValidating={isValidating}>
                                {t("common.Save")}
                            </SubmitButton>
                        </Flex>
                    </Flex>
                </Drawer.Content>
            </Drawer.Root>
        </Form.Root>
    );
});

export default BoardCommentForm;
