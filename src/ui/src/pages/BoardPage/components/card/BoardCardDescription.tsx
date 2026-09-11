import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Skeleton from "@/components/base/Skeleton";
import type { TEditor } from "@/components/Editor/editor-kit";
import { PlateEditor } from "@/components/Editor/plate-editor";
import { sanitizeEditorContent } from "@/components/Editor/utils";
import { BotModel, ProjectCard, ProjectCardComment } from "@/core/models";
import type { IEditorContent } from "@/core/models/Base";
import type { TUserLikeModel } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { useBoardCard, useBoardCardPanel } from "@/core/providers/BoardCardProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { useBoardCardSectionSaveActions } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import { EEditorType } from "@langboard/core/constants";
import { AIChatPlugin, AIPlugin } from "@platejs/ai/react";
import { memo, startTransition, type MouseEvent, type PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { toMarkdown } from "mdast-util-to-markdown";
import { gfmToMarkdown } from "mdast-util-gfm";
import { Utils } from "@langboard/core/utils";
import {
    captureCardCommentAnchor,
    normalizeAnchorPreview,
    resolveCardCommentAnchorElement,
    type ICardCommentAnchor,
} from "@/pages/BoardPage/components/card/comment/commentAnchor";

const FULL_COPY_TEXT_SAMPLE_LENGTH = 80;

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

function normalizeCopyText(value: string): string {
    return value
        .replace(/\uFEFF/g, "")
        .replace(/\s+/g, "")
        .trim();
}

function getRenderedDescriptionText(descriptionElement: HTMLElement): string {
    return Array.from(descriptionElement.querySelectorAll("[data-slate-editor]"))
        .map((editorElement) => editorElement.textContent ?? "")
        .join("\n");
}

function hasHiddenDescriptionChunks(descriptionElement: HTMLElement, showMoreText: string, showAllText: string): bool {
    return Array.from(descriptionElement.querySelectorAll("*")).some((element) => {
        const text = element.textContent?.trim();
        return text === showMoreText || text === showAllText;
    });
}

function isFullRenderedDescriptionSelection(descriptionElement: HTMLElement, selectedText: string, showMoreText: string, showAllText: string): bool {
    if (hasHiddenDescriptionChunks(descriptionElement, showMoreText, showAllText)) {
        return false;
    }

    const renderedText = normalizeCopyText(getRenderedDescriptionText(descriptionElement));
    const selected = normalizeCopyText(selectedText);
    if (!renderedText || !selected) {
        return false;
    }

    if (renderedText.length <= FULL_COPY_TEXT_SAMPLE_LENGTH * 2) {
        return selected === renderedText;
    }

    const head = renderedText.slice(0, FULL_COPY_TEXT_SAMPLE_LENGTH);
    const tail = renderedText.slice(-FULL_COPY_TEXT_SAMPLE_LENGTH);
    return selected.startsWith(head) && selected.endsWith(tail);
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

const BoardCardDescription = memo((): React.JSX.Element => {
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
    const comments = ProjectCardComment.Model.useModels((model) => model.card_uid === card.uid, [card.uid]);
    const description = card.useField("description");
    const [isEditing, setIsEditing] = useState(false);
    const [anchorComposer, setAnchorComposer] = useState<IAnchorComposerPosition | null>(null);
    const [anchorMarkers, setAnchorMarkers] = useState<IAnchorMarkerPosition[]>([]);
    const [anchorCommentSnapshots, setAnchorCommentSnapshots] = useState<Record<string, IAnchorCommentSnapshot>>({});
    const pointerDownPositionRef = useRef<{ x: number; y: number } | null>(null);
    const { registerSectionCancelHandler, registerSectionSaveHandler } = useBoardCardSectionSaveActions();
    const canEdit = hasRoleAction(ProjectRole.EAction.CardUpdate);
    const canStartEditing = canEdit && isCardEditing;
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

    const contentLines = description?.content?.split("\n").length ?? 0;
    const shouldCollapse = !isEditing && contentLines > MAX_COLLAPSE_LINES;
    const [visibleChunkCount, setVisibleChunkCount] = useState(1);
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

        const handleCopy = (event: ClipboardEvent) => {
            const descriptionElement = descriptionRef.current;
            const selection = window.getSelection();
            const selectedText = selection?.toString();

            if (!descriptionElement || !selection || !selectedText || !event.clipboardData) {
                return;
            }

            const containsSelectionNode = (node: Node | null) => node !== null && descriptionElement.contains(node);
            if (!containsSelectionNode(selection.anchorNode) && !containsSelectionNode(selection.focusNode)) {
                return;
            }

            const markdownContent = description?.content;
            const shouldCopyMarkdown =
                Utils.Type.isString(markdownContent) &&
                isFullRenderedDescriptionSelection(descriptionElement, selectedText, t("editor.Show more"), t("editor.Show all"));

            event.clipboardData.setData("text/plain", shouldCopyMarkdown ? markdownContent : selectedText);
            event.preventDefault();
        };

        document.addEventListener("copy", handleCopy, true);
        return () => document.removeEventListener("copy", handleCopy, true);
    }, [description, isEditing]);

    const handlePointerDown = useCallback(
        (e: PointerEvent<HTMLDivElement>) => {
            if (!canStartEditing || isEditing) {
                return;
            }

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
    }, [anchorCommentSnapshots, comments, description?.content, isEditing, shouldCollapse, visibleChunkCount]);

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
            {shouldCollapse ? (
                <CollapsibleDescriptionContent
                    description={description}
                    mentionables={mentionables}
                    cards={cards}
                    visibleChunkCount={visibleChunkCount}
                    setVisibleChunkCount={setVisibleChunkCount}
                />
            ) : (
                <Box>
                    <PlateEditor
                        value={description}
                        mentionables={mentionables}
                        linkables={cards}
                        currentUser={currentUser}
                        containerClassName="overflow-y-visible"
                        className={cn("h-full min-h-[calc(theme(spacing.56)_-_theme(spacing.8))]", isEditing ? "px-6 py-3" : "")}
                        readOnly={!isEditing}
                        editorType={EEditorType.CardDescription}
                        form={{
                            project_uid: projectUID,
                            card_uid: card.uid,
                        }}
                        placeholder={!isEditing ? t("card.No description") : undefined}
                        setValue={() => {}}
                        onCollaborativeValueReady={handleCollaborativeValueReady}
                        onCollaborativeValueResetReady={handleCollaborativeValueResetReady}
                        serializeOnChange={false}
                        focusOnReady={isEditing}
                        editorRef={editorRef}
                    />
                </Box>
            )}
        </Box>
    );
});

interface ICollapsibleDescriptionContentProps {
    description: IEditorContent | undefined;
    mentionables: TUserLikeModel[];
    cards: ProjectCard.TModel[];
    visibleChunkCount: number;
    setVisibleChunkCount: React.Dispatch<React.SetStateAction<number>>;
}

const MAX_COLLAPSE_LINES = 10;
const MAX_CHUNK_BLOCKS = 10;
const MAX_HEAVY_LIST_ITEMS = 6;
const MAX_HEAVY_PARAGRAPH_LENGTH = 1200;
const SHOW_ALL_BATCH_SIZE = 2;

interface IMarkdownNode {
    type?: string;
    children?: IMarkdownNode[];
    value?: string;
    alt?: string | null;
}

function countMarkdownListItems(node: IMarkdownNode | undefined): number {
    if (!node?.children) {
        return 0;
    }

    return node.children.reduce((count, child) => {
        if (child?.type !== "listItem") {
            return count;
        }

        return count + 1;
    }, 0);
}

function getMarkdownTextLength(node: IMarkdownNode | undefined): number {
    if (!node) {
        return 0;
    }

    const ownLength = Utils.Type.isString(node.value) ? node.value.length : Utils.Type.isString(node.alt) ? node.alt.length : 0;
    if (!node.children?.length) {
        return ownLength;
    }

    return ownLength + node.children.reduce((length, child) => length + getMarkdownTextLength(child), 0);
}

function isHeavyMarkdownBlock(node: IMarkdownNode | undefined): bool {
    if (!node?.type) {
        return false;
    }

    if (node.type === "table" || node.type === "code" || node.type === "blockquote") {
        return true;
    }

    if (node.type === "list") {
        return countMarkdownListItems(node) >= MAX_HEAVY_LIST_ITEMS;
    }

    if (node.type === "paragraph") {
        return getMarkdownTextLength(node) >= MAX_HEAVY_PARAGRAPH_LENGTH;
    }

    return false;
}

const CollapsibleDescriptionContent = memo((props: ICollapsibleDescriptionContentProps): React.JSX.Element => {
    const { description, mentionables, cards, visibleChunkCount, setVisibleChunkCount } = props;
    const [t] = useTranslation();
    const { projectUID, card, currentUser } = useBoardCard();
    const chunkContents = useMemo(() => {
        const content = description?.content ?? "";

        if (!sanitizeEditorContent(content)) {
            return [{ content: "" }];
        }

        const root = unified().use(remarkParse).use(remarkGfm).parse(content) as { children?: IMarkdownNode[] };
        const children = Array.isArray(root.children) ? root.children : [];

        if (children.length === 0) {
            return [{ content }];
        }

        const chunks: IEditorContent[] = [];
        let currentChunk: IMarkdownNode[] = [];

        const pushChunk = (chunkChildren: IMarkdownNode[]) => {
            if (chunkChildren.length === 0) {
                return;
            }

            chunks.push({
                content: toMarkdown({ type: "root", children: chunkChildren } as never, {
                    extensions: [gfmToMarkdown()],
                }),
            });
        };

        for (const child of children) {
            if (isHeavyMarkdownBlock(child)) {
                pushChunk(currentChunk);
                currentChunk = [];
                pushChunk([child]);
                continue;
            }

            currentChunk.push(child);
            if (currentChunk.length >= MAX_CHUNK_BLOCKS) {
                pushChunk(currentChunk);
                currentChunk = [];
            }
        }

        pushChunk(currentChunk);

        return chunks;
    }, [description]);
    const totalChunkCount = Math.max(1, chunkContents.length);
    const showAllFrameRef = useRef<number | null>(null);
    const clampedVisibleChunkCount = Math.min(visibleChunkCount, totalChunkCount);
    const hasMoreContent = clampedVisibleChunkCount < totalChunkCount;

    useEffect(() => {
        return () => {
            if (showAllFrameRef.current !== null) {
                cancelAnimationFrame(showAllFrameRef.current);
            }
        };
    }, []);

    const createChunk = useCallback(
        (chunkIndex: number) => {
            const chunkContent = chunkContents[chunkIndex] ?? { content: "" };

            return (
                <Box key={chunkIndex} className="[contain-intrinsic-size:auto_160px] [content-visibility:auto]">
                    <PlateEditor
                        value={chunkContent}
                        mentionables={mentionables}
                        linkables={cards}
                        currentUser={currentUser}
                        containerClassName="overflow-y-visible"
                        className="h-full min-h-0"
                        readOnly
                        editorType={EEditorType.CardDescription}
                        form={{
                            project_uid: projectUID,
                            card_uid: card.uid,
                        }}
                        placeholder={chunkIndex === 0 ? t("card.No description") : undefined}
                        setValue={() => {}}
                    />
                </Box>
            );
        },
        [chunkContents, mentionables, cards, currentUser, projectUID, card]
    );

    const handleExpand = useCallback((e: MouseEvent<HTMLDivElement> | PointerEvent<HTMLDivElement>) => {
        e.stopPropagation();
        e.preventDefault();
        setVisibleChunkCount((prev) => prev + 1);
    }, []);
    const handleExpandAll = useCallback(
        (e: MouseEvent<HTMLDivElement> | PointerEvent<HTMLDivElement>) => {
            e.stopPropagation();
            e.preventDefault();

            if (showAllFrameRef.current !== null) {
                cancelAnimationFrame(showAllFrameRef.current);
            }

            const expandNext = () => {
                startTransition(() => {
                    setVisibleChunkCount((prev) => {
                        const next = Math.min(prev + SHOW_ALL_BATCH_SIZE, totalChunkCount);

                        if (next < totalChunkCount) {
                            showAllFrameRef.current = requestAnimationFrame(expandNext);
                        } else {
                            showAllFrameRef.current = null;
                        }

                        return next;
                    });
                });
            };

            expandNext();
        },
        [totalChunkCount]
    );

    return (
        <Box position="relative">
            {Array.from({ length: clampedVisibleChunkCount }, (_, chunkIndex) => createChunk(chunkIndex))}
            {hasMoreContent && (
                <>
                    <Flex position="relative" justify="center" pb="2" z="50" gap="3" wrap>
                        <Flex
                            inline
                            items="center"
                            gap="1"
                            textSize="sm"
                            weight="semibold"
                            className="text-accent-foreground/70 transition-colors hover:text-accent-foreground"
                            cursor="pointer"
                            onPointerDown={handleExpand}
                        >
                            {t("editor.Show more")}
                            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                            </svg>
                        </Flex>
                        <Flex
                            inline
                            items="center"
                            gap="1"
                            textSize="sm"
                            weight="semibold"
                            className="text-accent-foreground/70 transition-colors hover:text-accent-foreground"
                            cursor="pointer"
                            onPointerDown={handleExpandAll}
                        >
                            {t("editor.Show all")}
                            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v14m-7-7h14" />
                            </svg>
                        </Flex>
                    </Flex>
                </>
            )}
        </Box>
    );
});

export default BoardCardDescription;
