import Dialog from "@/components/base/Dialog";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Skeleton from "@/components/base/Skeleton";
import Button from "@/components/base/Button";
import Collaborative from "@/components/Collaborative";
import useResizeEvent from "@/core/hooks/useResizeEvent";
import { useBoardCard } from "@/core/providers/BoardCardProvider";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { cn, measureTextAreaHeight } from "@/core/utils/ComponentUtils";
import { useBoardCardSectionSaveActions } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import BoardCardNotificationSettings from "@/pages/BoardPage/components/card/BoardCardNotificationSettings";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { type KeyboardEvent, type PointerEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export function SkeletonBoardCardTitle() {
    return (
        <Dialog.Title>
            <Skeleton h="8" className="w-1/3" />
        </Dialog.Title>
    );
}

function BoardCardTitle({ className, useDialogTitle = true }: { className?: string; useDialogTitle?: bool }): React.JSX.Element {
    const { setPageAliasRef } = usePageHeader();
    const { card, isCardEditing, canEditCard } = useBoardCard();
    const [t] = useTranslation();
    const { registerSectionCancelHandler, registerSectionSaveHandler } = useBoardCardSectionSaveActions();
    const title = card.useField("title");
    const titleSpanRef = useRef<HTMLSpanElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const updateCollaborativeTitleRef = useRef<((value: string) => void) | null>(null);
    const resetCollaborativeTitleRef = useRef<((value: string) => void) | null>(null);
    const [draftTitle, setDraftTitle] = useState(title);
    const [height, setHeight] = useState(0);
    const [isOpened, setIsOpened] = useState(false);
    const [isTitleWrapping, setIsTitleWrapping] = useState(false);
    const [titleMaxHeight, setTitleMaxHeight] = useState(32);
    const [showCollapse, setShowCollapse] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const canStartEditing = canEditCard && isCardEditing;

    const updateShowCollapse = useCallback(() => {
        const titleSpan = titleSpanRef.current;
        if (!titleSpan) {
            setShowCollapse(false);
            return;
        }

        const isOverflowed = isTitleWrapping ? showCollapse : titleSpan.scrollWidth > titleSpan.clientWidth;
        setShowCollapse(isOverflowed);
        setTitleMaxHeight(isTitleWrapping ? titleSpan.scrollHeight : 32);
    }, [isTitleWrapping, showCollapse]);

    const openTitle = useCallback(() => {
        const titleSpan = titleSpanRef.current;
        setIsOpened(true);
        setIsTitleWrapping(true);
        setTitleMaxHeight(titleSpan?.clientHeight || 32);

        requestAnimationFrame(() => {
            const nextTitleSpan = titleSpanRef.current;
            if (!nextTitleSpan) {
                return;
            }

            setTitleMaxHeight(nextTitleSpan.scrollHeight);
        });
    }, []);

    const closeTitle = useCallback(() => {
        const titleSpan = titleSpanRef.current;
        setIsOpened(false);
        setTitleMaxHeight(titleSpan?.scrollHeight || 32);

        requestAnimationFrame(() => {
            setTitleMaxHeight(32);
        });

        window.setTimeout(() => {
            setIsTitleWrapping(false);
        }, 200);
    }, []);

    const syncHeight = useCallback(() => {
        if (!textareaRef.current) {
            return;
        }

        setHeight(measureTextAreaHeight(textareaRef.current));
    }, []);

    const handleStartEditing = useCallback(
        (e: PointerEvent<HTMLSpanElement>) => {
            if (!canStartEditing) {
                return;
            }

            e.preventDefault();
            e.stopPropagation();

            requestAnimationFrame(() => {
                setIsEditing(true);
            });
        },
        [canStartEditing]
    );

    const handleToggleOpened = useCallback(() => {
        if (isOpened) {
            closeTitle();
            return;
        }

        openTitle();
    }, [closeTitle, isOpened, openTitle]);

    const handleTitleValueChange = useCallback(
        (nextTitle: string) => {
            setDraftTitle(nextTitle);
            requestAnimationFrame(syncHeight);
        },
        [syncHeight]
    );

    const handleCollaborativeValueReady = useCallback((updateValue: ((value: string) => void) | null) => {
        updateCollaborativeTitleRef.current = updateValue;
    }, []);

    const handleCollaborativeValueResetReady = useCallback((resetValue: ((value: string) => void) | null) => {
        resetCollaborativeTitleRef.current = resetValue;
    }, []);

    const handleTitleKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key !== "Enter") {
            return;
        }

        e.preventDefault();
        e.stopPropagation();
    }, []);

    const saveTitle = useCallback(() => {
        const nextTitle = draftTitle.trim();
        const originalTitle = title.trim();
        if (!nextTitle || nextTitle === originalTitle) {
            resetCollaborativeTitleRef.current?.(title);
            setDraftTitle(title);
            return null;
        }

        return { title: nextTitle };
    }, [draftTitle, title]);

    const cancelTitle = useCallback(() => {
        resetCollaborativeTitleRef.current?.(title);
        setDraftTitle(title);
        setIsEditing(false);
    }, [title]);

    useEffect(() => {
        setPageAliasRef.current(title);
    }, [title]);

    useEffect(() => {
        if (!isCardEditing) {
            setIsEditing(false);
            setDraftTitle(title);
        }
    }, [isCardEditing, title]);

    useLayoutEffect(() => {
        if (!isEditing) {
            return;
        }

        syncHeight();
        textareaRef.current?.focus();
    }, [isEditing, syncHeight]);

    useLayoutEffect(() => {
        requestAnimationFrame(updateShowCollapse);
    }, [title, updateShowCollapse]);

    useResizeEvent({ doneCallback: updateShowCollapse }, [updateShowCollapse]);

    useEffect(() => registerSectionSaveHandler("title", saveTitle), [registerSectionSaveHandler, saveTitle]);
    useEffect(() => registerSectionCancelHandler("title", cancelTitle), [cancelTitle, registerSectionCancelHandler]);

    const Title = useDialogTitle ? Dialog.Title : "div";

    return (
        <Title className={cn("mr-20 min-w-0 flex-1 text-2xl xs:mr-[88px]", className)}>
            {!isEditing ? (
                <Flex className="min-w-0">
                    <span
                        className={cn(
                            "block min-w-0 flex-1 overflow-hidden transition-[max-height] duration-200 ease-in-out",
                            isTitleWrapping ? "whitespace-normal break-all" : "truncate",
                            canStartEditing && "cursor-text rounded-sm hover:bg-accent/40"
                        )}
                        style={{ maxHeight: titleMaxHeight }}
                        ref={titleSpanRef}
                        onPointerDown={handleStartEditing}
                    >
                        {title}
                    </span>
                    <Flex items="start" gap="1" ml="1" className="shrink-0">
                        <Button
                            variant="ghost"
                            size="icon-sm"
                            onClick={handleToggleOpened}
                            title={t(`card.${isOpened ? "Hide" : "Show"} title`)}
                            className={showCollapse ? "" : "hidden"}
                        >
                            <IconComponent icon="chevron-down" size="5" className={cn("transition-all", isOpened ? "rotate-180" : "")} />
                        </Button>
                        <BoardCardNotificationSettings key={`board-card-notification-settings-${card.uid}`} />
                    </Flex>
                </Flex>
            ) : (
                <Collaborative.Textarea
                    ref={textareaRef}
                    collaborationType={EEditorCollaborationType.Card}
                    uid={card.uid}
                    section="title"
                    field="title"
                    defaultValue={title}
                    resetSyncedValueToDefault
                    className={cn(
                        "min-h-8 break-all rounded-none border-x-0 border-t-0 p-0 text-2xl scrollbar-hide",
                        "focus-visible:border-b-primary focus-visible:ring-0"
                    )}
                    resize="none"
                    style={{ height }}
                    onCollaborativeValueReady={handleCollaborativeValueReady}
                    onCollaborativeValueResetReady={handleCollaborativeValueResetReady}
                    onValueChange={handleTitleValueChange}
                    onKeyDown={handleTitleKeyDown}
                />
            )}
        </Title>
    );
}

export default BoardCardTitle;
