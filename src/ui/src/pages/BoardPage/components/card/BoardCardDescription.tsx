import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Skeleton from "@/components/base/Skeleton";
import type { TEditor } from "@/components/Editor/editor-kit";
import { PlateEditor } from "@/components/Editor/plate-editor";
import { sanitizeEditorContent } from "@/components/Editor/utils";
import { BotModel, ProjectCard, ProjectCardComment } from "@/core/models";
import type { TUserLikeModel } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { useBoardCard, useBoardCardPanel } from "@/core/providers/BoardCardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { useBoardCardSectionSaveActions } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import useGetCardComments from "@/controllers/api/card/comment/useGetCardComments";
import { EEditorType } from "@langboard/core/constants";
import { AIChatPlugin, AIPlugin } from "@platejs/ai/react";
import { memo, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Utils } from "@langboard/core/utils";
import { VirtualizedDescriptionContent } from "@/pages/BoardPage/components/card/description/VirtualizedDescriptionContent";
import { buildDescriptionChunks } from "@/pages/BoardPage/components/card/description/descriptionChunks";
import {
    captureCardCommentAnchor,
    normalizeAnchorPreview,
    resolveCardCommentAnchorElement,
    type ICardCommentAnchor,
} from "@/pages/BoardPage/components/card/comment/commentAnchor";

interface IAnchorComposerPosition {
    anchor: ICardCommentAnchor;
    left: number;
    top: number;
}

interface IAnchorMarkerPosition {
    commentUID: string;
    quote: string;
    commentPreview: string;
    top: number;
}

interface IAnchorCommentSnapshot {
    anchor: ICardCommentAnchor | null;
    content: string;
}

interface IAnchorCommentSubscriptionProps {
    comment: ProjectCardComment.TModel;
    onChange: (commentUID: string, snapshot: IAnchorCommentSnapshot | null) => void;
}

function AnchorCommentSubscription({ comment, onChange }: IAnchorCommentSubscriptionProps) {
    const anchor = comment.useField("anchor") ?? null;
    const content = comment.useField("content")?.content ?? "";

    useEffect(() => {
        onChange(comment.uid, { anchor, content });
    }, [anchor, comment.uid, content, onChange]);

    useEffect(() => () => onChange(comment.uid, null), [comment.uid, onChange]);

    return null;
}

interface IBoardCardDescriptionProps {
    scrollParentRef: React.RefObject<HTMLDivElement | null>;
}

export function SkeletonBoardCardDescription() {
    return (
        <Box>
            <Box h="full" className="min-h-[calc(theme(spacing.56)_-_theme(spacing.8))] text-muted-foreground">
                <Skeleton w="full" className="h-[calc(theme(spacing.56)_-_theme(spacing.8))]" />
            </Box>
        </Box>
    );
}

const BoardCardDescription = memo(({ scrollParentRef }: IBoardCardDescriptionProps): React.JSX.Element => {
    const { projectUID, card, currentUser, hasRoleAction, isCardEditing, anchoredCommentRef } = useBoardCard();
    const { setIsCommentPanelOpen } = useBoardCardPanel();
    const [t] = useTranslation();
    const editorRef = useRef<TEditor>(null);
    const descriptionRef = useRef<HTMLDivElement>(null);
    const updateCollaborativeDescriptionRef = useRef<((value: string) => void) | null>(null);
    const resetCollaborativeDescriptionRef = useRef<((value: string) => void) | null>(null);
    const projectMembers = card.useForeignFieldArray("project_members");
    const bots = BotModel.Model.useModels(() => true);
    const mentionables = useMemo(() => [...projectMembers, ...bots], [projectMembers, bots]);
    const cards = ProjectCard.Model.useModels((model) => model.uid !== card.uid && model.project_uid === projectUID, [projectUID, card]);
    const modelComments = ProjectCardComment.Model.useModels((model) => model.card_uid === card.uid, [card.uid]);
    const { data: commentsData } = useGetCardComments({ project_uid: projectUID, card_uid: card.uid });
    const comments = commentsData?.comments ?? modelComments;
    const description = card.useField("description");
    const [isEditing, setIsEditing] = useState(false);
    const [anchorComposer, setAnchorComposer] = useState<IAnchorComposerPosition | null>(null);
    const [anchorMarkers, setAnchorMarkers] = useState<IAnchorMarkerPosition[]>([]);
    const [anchorCommentSnapshots, setAnchorCommentSnapshots] = useState<Record<string, IAnchorCommentSnapshot>>({});
    const pointerDownPositionRef = useRef<{ x: number; y: number } | null>(null);
    const descriptionSelectAllRef = useRef(false);
    const { registerSectionCancelHandler, registerSectionSaveHandler } = useBoardCardSectionSaveActions();
    const canEdit = hasRoleAction(ProjectRole.EAction.CardUpdate);
    const canStartEditing = canEdit && isCardEditing;
    useEffect(() => {
        if (canStartEditing) {
            setIsEditing(true);
        }
    }, [canStartEditing]);
    const updateAnchorCommentSnapshot = useCallback((commentUID: string, snapshot: IAnchorCommentSnapshot | null) => {
        setAnchorCommentSnapshots((current) => {
            if (!snapshot) {
                if (!(commentUID in current)) {
                    return current;
                }
                const next = { ...current };
                delete next[commentUID];
                return next;
            }
            const previous = current[commentUID];
            if (previous?.anchor === snapshot.anchor && previous.content === snapshot.content) {
                return current;
            }
            return { ...current, [commentUID]: snapshot };
        });
    }, []);
    const stopEditing = useCallback(() => {
        if (!editorRef.current) {
            return;
        }

        const aiTransforms = editorRef.current.getTransforms(AIPlugin);
        const aiChatApi = editorRef.current.getApi(AIChatPlugin);
        aiChatApi.aiChat?.stop?.();
        aiTransforms.ai?.undo?.();
        aiChatApi.aiChat?.hide?.();
    }, []);

    const chunks = useMemo(() => buildDescriptionChunks(description?.content ?? ""), [description?.content]);
    const handleCollaborativeValueReady = useCallback((updateValue: ((value: string) => void) | null) => {
        updateCollaborativeDescriptionRef.current = updateValue;
    }, []);

    const handleCollaborativeValueResetReady = useCallback((resetValue: ((value: string) => void) | null) => {
        resetCollaborativeDescriptionRef.current = resetValue;
    }, []);

    const handleSave = useCallback(() => {
        const nextContent = sanitizeEditorContent(editorRef.current?.api.markdown.serialize() ?? description?.content ?? "");
        const originalContent = sanitizeEditorContent(description?.content ?? "");

        if (nextContent === originalContent) {
            resetCollaborativeDescriptionRef.current?.(description?.content ?? "");
            setIsEditing(false);
            return null;
        }

        return {
            description: {
                ...(description ?? {}),
                content: nextContent,
            },
        };
    }, [description]);

    const handleCancel = useCallback(() => {
        resetCollaborativeDescriptionRef.current?.(description?.content ?? "");
        stopEditing();
        setIsEditing(false);
    }, [description, stopEditing]);

    useEffect(() => {
        if (!isCardEditing && isEditing) {
            stopEditing();
            setIsEditing(false);
        }
    }, [isCardEditing, isEditing, stopEditing]);

    useEffect(() => {
        if (isEditing) {
            return;
        }

        const containsSelectionNode = (node: Node | null) => node !== null && descriptionElement.contains(node);
        const handleSelectAll = (event: KeyboardEvent) => {
            if (event.key !== "a" || !(event.metaKey || event.ctrlKey)) {
                return;
            }

            const selection = window.getSelection();
            if (containsSelectionNode(selection?.anchorNode ?? null) || containsSelectionNode(selection?.focusNode ?? null)) {
                descriptionSelectAllRef.current = true;
            }
        };

        const handleCopy = (event: ClipboardEvent) => {
            const descriptionElement = descriptionRef.current;
            const selection = window.getSelection();
            const selectedText = selection?.toString();

            if (!descriptionElement || !selection || !selectedText || !event.clipboardData) {
                return;
            }

            if (!containsSelectionNode(selection.anchorNode) && !containsSelectionNode(selection.focusNode)) {
                return;
            }

            const markdownContent = description?.content;
            const shouldCopyMarkdown = Utils.Type.isString(markdownContent) && descriptionSelectAllRef.current;
            descriptionSelectAllRef.current = false;

            event.clipboardData.setData("text/plain", shouldCopyMarkdown ? markdownContent : selectedText);
            event.preventDefault();
        };

        document.addEventListener("keydown", handleSelectAll, true);
        document.addEventListener("copy", handleCopy, true);
        return () => {
            document.removeEventListener("keydown", handleSelectAll, true);
            document.removeEventListener("copy", handleCopy, true);
        };
    }, [description, isEditing]);

    const handlePointerDown = useCallback(
        (e: PointerEvent<HTMLDivElement>) => {
            if (!canStartEditing || isEditing) {
                return;
            }

            descriptionSelectAllRef.current = false;
            pointerDownPositionRef.current = {
                x: e.clientX,
                y: e.clientY,
            };
        },
        [canStartEditing, isEditing]
    );

    const captureSelection = useCallback(() => {
        if (isEditing) {
            setAnchorComposer(null);
            return;
        }
        const root = descriptionRef.current;
        const selection = window.getSelection();
        const anchor = root ? captureCardCommentAnchor(root, selection) : null;
        if (!root || !anchor || !selection?.rangeCount) {
            setAnchorComposer(null);
            return;
        }
        const rangeRect = selection.getRangeAt(0).getBoundingClientRect();
        const rootRect = root.getBoundingClientRect();
        setAnchorComposer({
            anchor,
            left: Math.max(8, Math.min(rangeRect.left - rootRect.left, rootRect.width - 112)),
            top: Math.max(0, rangeRect.bottom - rootRect.top + 6),
        });
    }, [isEditing]);

    const handlePointerUp = useCallback(
        (e: PointerEvent<HTMLDivElement>) => {
            captureSelection();
            if ((e.target as HTMLElement).closest("button")) {
                pointerDownPositionRef.current = null;
                return;
            }
            const pointerDownPosition = pointerDownPositionRef.current;
            pointerDownPositionRef.current = null;
            if (!canStartEditing || isEditing || !pointerDownPosition) {
                return;
            }

            const movedDistance = Math.hypot(e.clientX - pointerDownPosition.x, e.clientY - pointerDownPosition.y);
            if (movedDistance > 4 || window.getSelection()?.toString()) {
                return;
            }

            requestAnimationFrame(() => {
                setIsEditing(true);
            });
        },
        [canStartEditing, captureSelection, isEditing]
    );

    useEffect(() => {
        const root = descriptionRef.current;
        if (!root || isEditing) {
            setAnchorMarkers([]);
            return;
        }

        const updateMarkers = () => {
            const rootRect = root.getBoundingClientRect();
            const seen = new Map<number, number>();
            const next = comments.flatMap((comment) => {
                const snapshot = anchorCommentSnapshots[comment.uid];
                const anchor = snapshot?.anchor;
                if (!anchor) {
                    return [];
                }
                const block = resolveCardCommentAnchorElement(root, anchor);
                if (!block) {
                    return [];
                }
                const blockTop = block.getBoundingClientRect().top - rootRect.top;
                const roundedTop = Math.round(blockTop);
                const stackIndex = seen.get(roundedTop) ?? 0;
                seen.set(roundedTop, stackIndex + 1);
                return [
                    {
                        commentUID: comment.uid,
                        quote: anchor.exact,
                        commentPreview: normalizeAnchorPreview(snapshot.content),
                        top: blockTop + stackIndex * 24,
                    },
                ];
            });
            setAnchorMarkers(next);
        };

        updateMarkers();
        const observer = new ResizeObserver(updateMarkers);
        observer.observe(root);
        return () => observer.disconnect();
    }, [anchorCommentSnapshots, comments, description?.content, isEditing, chunks.length]);

    const openAnchoredComment = useCallback(
        (commentUID: string) => {
            setIsCommentPanelOpen(true);
            window.setTimeout(() => {
                document.querySelector<HTMLElement>(`[data-card-comment-uid="${CSS.escape(commentUID)}"]`)?.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                });
            }, 100);
        },
        [setIsCommentPanelOpen]
    );

    useEffect(() => registerSectionSaveHandler("description", handleSave), [handleSave, registerSectionSaveHandler]);
    useEffect(() => registerSectionCancelHandler("description", handleCancel), [handleCancel, registerSectionCancelHandler]);

    return (
        <Box
            ref={descriptionRef}
            data-card-description
            className={cn("relative", canStartEditing && !isEditing && "cursor-text rounded-md transition-colors hover:bg-accent/20")}
            onPointerDown={handlePointerDown}
            onPointerUp={handlePointerUp}
        >
            {comments.map((comment) => (
                <AnchorCommentSubscription key={comment.uid} comment={comment} onChange={updateAnchorCommentSnapshot} />
            ))}
            {anchorComposer && (
                <Button
                    size="sm"
                    className="absolute z-30 h-8 gap-1 rounded-full shadow-lg"
                    style={{ left: anchorComposer.left, top: anchorComposer.top }}
                    onPointerDown={(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                    }}
                    onClick={() => {
                        anchoredCommentRef.current(anchorComposer.anchor);
                        setAnchorComposer(null);
                        window.getSelection()?.removeAllRanges();
                    }}
                >
                    <IconComponent icon="message-square" size="4" />
                    {t("card.Comment on selection")}
                </Button>
            )}
            {anchorMarkers.map((marker) => (
                <button
                    key={marker.commentUID}
                    type="button"
                    className={cn(
                        "group absolute right-1 z-20 flex size-5 items-center justify-center rounded-full border border-brand/40",
                        "bg-brand/15 text-brand shadow-sm transition-transform hover:scale-110"
                    )}
                    style={{ top: marker.top }}
                    title={marker.quote}
                    aria-label={t("card.Open anchored comment")}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={() => openAnchoredComment(marker.commentUID)}
                >
                    <IconComponent icon="message-square" size="3" />
                    <span
                        className={cn(
                            "pointer-events-none absolute right-6 top-1/2 hidden w-64 -translate-y-1/2 rounded-lg border",
                            "bg-popover p-2 text-left text-popover-foreground shadow-xl group-hover:block group-focus-visible:block"
                        )}
                    >
                        <span className="block truncate text-[11px] font-medium text-brand">“{marker.quote}”</span>
                        <span className="mt-1 line-clamp-3 block text-xs leading-5 text-muted-foreground">
                            {marker.commentPreview || t("card.Open anchored comment")}
                        </span>
                    </span>
                </button>
            ))}
            {isEditing ? (
                <PlateEditor
                    value={description}
                    mentionables={mentionables}
                    linkables={cards}
                    currentUser={currentUser}
                    containerClassName="overflow-y-visible"
                    className="h-full min-h-[calc(theme(spacing.56)_-_theme(spacing.8))] px-6 py-3"
                    readOnly={false}
                    editorType={EEditorType.CardDescription}
                    form={{
                        project_uid: projectUID,
                        card_uid: card.uid,
                    }}
                    placeholder={t("card.No description")}
                    setValue={() => {}}
                    authoritativeCollaborativeValue={description?.content ?? ""}
                    onCollaborativeValueReady={handleCollaborativeValueReady}
                    onCollaborativeValueResetReady={handleCollaborativeValueResetReady}
                    serializeOnChange={false}
                    focusOnReady
                    editorRef={editorRef}
                />
            ) : (
                <VirtualizedDescriptionContent
                    chunks={chunks}
                    currentUser={currentUser}
                    mentionables={mentionables}
                    cards={cards}
                    projectUID={projectUID}
                    cardUID={card.uid}
                    scrollParentRef={scrollParentRef}
                />
            )}
        </Box>
    );
});

export default BoardCardDescription;
