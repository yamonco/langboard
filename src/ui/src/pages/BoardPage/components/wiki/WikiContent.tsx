import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Skeleton from "@/components/base/Skeleton";
import Toast from "@/components/base/Toast";
import { TEditor } from "@/components/Editor/editor-kit";
import { PlateEditor } from "@/components/Editor/plate-editor";
import { sanitizeEditorContent } from "@/components/Editor/utils";
import useChangeWikiDetails from "@/controllers/api/wiki/useChangeWikiDetails";
import useCreateWikiLinkedCard from "@/controllers/api/wiki/useCreateWikiLinkedCard";
import useBoardUIWikiDeletedHandlers from "@/controllers/socket/wiki/useBoardUIWikiDeletedHandlers";
import useCardDeletedHandlers from "@/controllers/socket/card/useCardDeletedHandlers";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { BotModel, ProjectWiki } from "@/core/models";
import { useBoardWiki } from "@/core/providers/BoardWikiProvider";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { useBoardWikiUnsavedActions } from "@/pages/BoardPage/components/wiki/BoardWikiUnsavedProvider";
import WikiPrivateOption, { SkeletonWikiPrivateOption } from "@/pages/BoardPage/components/wiki/WikiPrivateOption";
import WikiTitle from "@/pages/BoardPage/components/wiki/WikiTitle";
import { EEditorType } from "@langboard/core/constants";
import { EHttpStatus } from "@langboard/core/enums";
import { ProjectRole } from "@/core/models/roles";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { AIChatPlugin, AIPlugin } from "@platejs/ai/react";
import { memo, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IWikiContentProps {
    wiki: ProjectWiki.TModel;
}

export function SkeletonWikiContent() {
    return (
        <Box mt="2">
            <SkeletonWikiPrivateOption />
            <Box p="2">
                <Skeleton h="8" className="w-2/3 md:w-1/3" />
            </Box>
            <Box position="relative" px="6" py="3" className="min-h-[calc(100vh_-_theme(spacing.56))]">
                <Skeleton position="absolute" className="h-3/5 w-4/5 md:w-3/5" />
            </Box>
        </Box>
    );
}

const WikiContent = memo(({ wiki }: IWikiContentProps) => {
    const navigate = usePageNavigateRef();
    const {
        project,
        wikis: flatWikis,
        socket,
        projectMembers,
        currentUser,
        changeTab,
        canEditWiki,
        isWikiEditing,
        setIsWikiEditing,
    } = useBoardWiki();
    const [t] = useTranslation();
    const {
        markSectionDirty,
        resetSection,
        getHasUnsavedChanges,
        registerSectionSaveHandler,
        registerSectionCancelHandler,
        saveDirtySections,
        cancelDirtySections,
    } = useBoardWikiUnsavedActions();
    const { mutateAsync: changeWikiDetailsMutateAsync } = useChangeWikiDetails("content", { interceptToast: true });
    const isPublic = wiki.useField("is_public");
    const assignedMembers = wiki.useForeignFieldArray("assigned_members");
    const bots = BotModel.Model.useModels(() => true);
    const wikis = useMemo(() => flatWikis.filter((w) => w.uid !== wiki.uid), [flatWikis, wiki]);
    const mentionables = useMemo(
        () => [...(isPublic ? projectMembers : assignedMembers), ...bots],
        [isPublic, assignedMembers, projectMembers, bots]
    );
    const content = wiki.useField("content");
    const linkedCardUID = wiki.useField("linked_card_uid");
    const roleActions = project.useField("current_auth_role_actions");
    const { hasRoleAction } = useRoleActionFilter(roleActions);
    const { mutateAsync: createLinkedCard, isPending: isCreatingLinkedCard } = useCreateWikiLinkedCard({ interceptToast: true });
    const canStartEditing = canEditWiki(wiki.uid);
    const canCreateLinkedCard = canStartEditing && hasRoleAction(ProjectRole.EAction.CardUpdate);
    const editorRef = useRef<TEditor>(null);
    const [isEditing, setIsEditing] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const stopEditing = useCallback(() => {
        if (!editorRef.current) {
            return;
        }

        const aiTransforms = editorRef.current.getTransforms(AIPlugin);
        const aiChatApi = editorRef.current.getApi(AIChatPlugin);
        aiChatApi.aiChat.stop();
        aiTransforms.ai.undo();
        aiChatApi.aiChat.hide();
    }, []);
    const handleEditorChange = useCallback(
        (editor: TEditor) => {
            const hasContentChange = editor.operations.some((operation) => operation.type !== "set_selection");
            if (!hasContentChange) {
                return;
            }

            markSectionDirty("content", true);
        },
        [markSectionDirty]
    );
    const handleSave = useCallback(async () => {
        const nextContent = sanitizeEditorContent(editorRef.current?.api.markdown.serialize() ?? content?.content ?? "");
        const originalContent = sanitizeEditorContent(content?.content ?? "");

        if (nextContent === originalContent) {
            resetSection("content");
            setIsEditing(false);
            return;
        }

        const promise = changeWikiDetailsMutateAsync({
            project_uid: project.uid,
            wiki_uid: wiki.uid,
            content: {
                ...(content ?? {}),
                content: nextContent,
            },
        });

        await Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler(
                    {
                        [EHttpStatus.HTTP_403_FORBIDDEN]: {
                            after: () => navigate(ROUTES.BOARD.WIKI(project.uid)),
                        },
                    },
                    messageRef
                );

                handle(error);
                return messageRef.message;
            },
            success: () => {
                resetSection("content");
                setIsEditing(false);
                return t("successes.Content changed successfully.");
            },
        });
    }, [changeWikiDetailsMutateAsync, content, project, resetSection, wiki]);
    const handleCancel = useCallback(() => {
        if (!isEditing) {
            return;
        }

        resetSection("content");
        stopEditing();
        setIsEditing(false);
    }, [isEditing, resetSection, stopEditing]);
    const boardUIWikiDeletedHandlers = useMemo(
        () =>
            useBoardUIWikiDeletedHandlers({
                projectUID: project.uid,
                wiki,
                callback: () => {
                    navigate(ROUTES.BOARD.WIKI(project.uid));
                },
            }),
        []
    );
    const linkedCardDeletedHandler = useMemo(
        () =>
            linkedCardUID
                ? useCardDeletedHandlers({
                      projectUID: project.uid,
                      cardUID: linkedCardUID,
                      callback: () => {
                          wiki.linked_card_uid = undefined;
                      },
                  })
                : null,
        [linkedCardUID, project, wiki]
    );
    const wikiSocketHandlers = useMemo(
        () => (linkedCardDeletedHandler ? [boardUIWikiDeletedHandlers, linkedCardDeletedHandler] : [boardUIWikiDeletedHandlers]),
        [boardUIWikiDeletedHandlers, linkedCardDeletedHandler]
    );

    useSwitchSocketHandlers({
        socket,
        handlers: wikiSocketHandlers,
        dependencies: wikiSocketHandlers,
    });

    useEffect(() => {
        if (!isWikiEditing && isEditing && !getHasUnsavedChanges()) {
            stopEditing();
            setIsEditing(false);
        }
    }, [getHasUnsavedChanges, isEditing, isWikiEditing, stopEditing]);

    const handleStartEditing = useCallback(
        (e: PointerEvent<HTMLDivElement>) => {
            if (!isWikiEditing || !canStartEditing || isEditing) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            requestAnimationFrame(() => {
                setIsEditing(true);
            });
        },
        [canStartEditing, isEditing, isWikiEditing]
    );

    useEffect(() => registerSectionSaveHandler("content", handleSave), [handleSave, registerSectionSaveHandler]);
    useEffect(() => registerSectionCancelHandler("content", handleCancel), [handleCancel, registerSectionCancelHandler]);

    const enterEditMode = useCallback(() => {
        if (!canStartEditing) {
            return;
        }

        setIsWikiEditing(true);
    }, [canStartEditing, setIsWikiEditing]);

    const handleSaveEditing = useCallback(async () => {
        if (isSaving) {
            return;
        }

        setIsSaving(true);

        try {
            if (getHasUnsavedChanges()) {
                const isSaved = await saveDirtySections();
                if (!isSaved || getHasUnsavedChanges()) {
                    Toast.Add.error(t("card.unsavedChanges.Keep editing"));
                    return;
                }
            }

            setIsWikiEditing(false);
        } finally {
            setIsSaving(false);
        }
    }, [getHasUnsavedChanges, isSaving, saveDirtySections, setIsWikiEditing]);

    const handleCancelEditing = useCallback(() => {
        cancelDirtySections();
        setIsWikiEditing(false);
    }, [cancelDirtySections, setIsWikiEditing]);

    return (
        <Box className="max-h-[calc(100vh_-_theme(spacing.36))] overflow-y-auto pb-20 md:pb-0">
            <WikiPrivateOption wiki={wiki} changeTab={changeTab} />
            <WikiTitle wiki={wiki} />
            <Box
                onPointerDown={handleStartEditing}
                position="relative"
                data-wiki-content
                className={cn(canStartEditing && !isEditing && "cursor-text rounded-md transition-colors hover:bg-accent/20")}
            >
                <PlateEditor
                    value={content}
                    currentUser={currentUser}
                    mentionables={mentionables}
                    linkables={wikis}
                    className={cn(
                        "h-full px-6 py-3",
                        isEditing
                            ? cn(
                                  "max-h-[calc(100vh_-_theme(spacing.72)_-_theme(spacing.6)_-_theme(spacing.20)_-_1px)]",
                                  "min-h-[calc(100vh_-_theme(spacing.72)_-_theme(spacing.6)_-_theme(spacing.20)_-_1px)]"
                              )
                            : cn(
                                  "max-h-[calc(100vh_-_theme(spacing.64)_-_theme(spacing.5)_-_theme(spacing.20))]",
                                  "min-h-[calc(100vh_-_theme(spacing.64)_-_theme(spacing.5)_-_theme(spacing.20))]"
                              )
                    )}
                    readOnly={!isEditing}
                    editorType={EEditorType.WikiContent}
                    form={{
                        project_uid: project.uid,
                        wiki_uid: wiki.uid,
                    }}
                    placeholder={!isEditing ? t("wiki.No content") : undefined}
                    setValue={() => {}}
                    onEditorChange={handleEditorChange}
                    serializeOnChange={false}
                    editorRef={editorRef}
                    focusOnReady={isEditing}
                />
            </Box>
            <Flex items="center" justify="start" pt="2" mx="2" gap="2" className="border-t">
                {canStartEditing && (
                    <>
                        {!isWikiEditing ? (
                            <Button type="button" variant="default" onClick={enterEditMode}>
                                {t("common.Edit")}
                            </Button>
                        ) : (
                            <>
                                <Button type="button" variant="secondary" onClick={handleCancelEditing}>
                                    {t("common.Cancel")}
                                </Button>
                                <Button type="button" variant="default" disabled={isSaving} onClick={handleSaveEditing}>
                                    {t("common.Save")}
                                </Button>
                            </>
                        )}
                    </>
                )}
                <Button type="button" variant="secondary" onClick={() => navigate(ROUTES.BOARD.WIKI_ACTIVITY(project.uid, wiki.uid))}>
                    {t("board.Activity")}
                </Button>
                <Button type="button" variant="secondary" onClick={() => navigate(ROUTES.BOARD.WIKI_METADATA(project.uid, wiki.uid))}>
                    {t("metadata.Metadata")}
                </Button>
                {linkedCardUID ? (
                    <Button type="button" variant="secondary" onClick={() => navigate(ROUTES.BOARD.CARD(project.uid, linkedCardUID))}>
                        {t("wiki.View on board")}
                    </Button>
                ) : (
                    canCreateLinkedCard && (
                        <Button
                            type="button"
                            variant="secondary"
                            disabled={isCreatingLinkedCard}
                            onClick={async () => {
                                const promise = createLinkedCard({ project_uid: project.uid, wiki_uid: wiki.uid });
                                Toast.Add.promise(promise, {
                                    loading: t("common.Creating..."),
                                    error: (error) => {
                                        const messageRef = { message: "" };
                                        const { handle } = setupApiErrorHandler({}, messageRef);
                                        handle(error);
                                        return messageRef.message;
                                    },
                                    success: ({ created }) => (created ? t("wiki.Linked card created") : t("wiki.Linked card already exists")),
                                });
                                try {
                                    const { card } = await promise;
                                    wiki.linked_card_uid = card.uid;
                                    navigate(ROUTES.BOARD.CARD(project.uid, card.uid));
                                } catch {
                                    // The toast above owns the error presentation.
                                }
                            }}
                        >
                            {t("wiki.Show on board")}
                        </Button>
                    )
                )}
            </Flex>
        </Box>
    );
});

export default WikiContent;
