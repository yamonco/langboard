import Dialog from "@/components/base/Dialog";
import { isNotificationInteraction } from "@/components/Header/useNotificationNavigation";
import { CARD_WINDOW_EMBEDDED_OVERLAY_CLASS, CARD_WINDOW_HEIGHT_CLASS, CARD_WINDOW_OVERLAY_CLASS } from "./cardWindowLayout";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useAuth } from "@/core/providers/AuthProvider";
import { ROUTES } from "@/core/routing/constants";
import { getEditorStore } from "@/core/stores/EditorStore";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCard from "@/pages/BoardPage/components/card/BoardCard";
import { BoardCardSectionSaveProvider } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import { EHttpStatus } from "@langboard/core/enums";
import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Navigate, useParams } from "react-router";
import { useBoardController } from "@/core/providers/BoardController";
import {
    CARD_ANIMATION_DURATION_MS,
    closedTransform,
    prefersReducedMotion,
    takeCardOrigin,
    type CardRect,
} from "@/pages/BoardPage/components/board/CardAnimation";

interface IBoardCardPageProps {
    projectUID?: string;
    cardUID?: string;
    embedded?: bool;
    isExpanded?: bool;
    setIsExpanded?: React.Dispatch<React.SetStateAction<bool>>;
}

const BoardCardPageComponent = ({
    projectUID: projectUIDProp,
    cardUID: cardUIDProp,
    embedded = false,
    isExpanded: controlledIsExpanded,
    setIsExpanded: controlledSetIsExpanded,
}: IBoardCardPageProps) => {
    const navigate = usePageNavigateRef();
    const { currentUser } = useAuth();
    const params = useParams();
    const projectUID = projectUIDProp ?? params.projectUID;
    const cardUID = cardUIDProp ?? params.cardUID;
    const viewportRef = useRef<HTMLDivElement | null>(null);
    const contentRef = useRef<HTMLDivElement | null>(null);
    const originRef = useRef<CardRect | null | undefined>(undefined);
    const closeTimerRef = useRef<number | null>(null);
    const closingRef = useRef(false);
    const finishedCloseRef = useRef(false);
    const [isClosing, setIsClosing] = useState(false);
    const isCardEditingRef = useRef(false);
    const cancelCardEditRef = useRef<(() => void) | null>(null);
    const [isComposing, setIsComposing] = useState(false);
    const [localIsExpanded, setLocalIsExpanded] = useState(false);
    const isExpanded = controlledIsExpanded ?? localIsExpanded;
    const setIsExpanded = controlledSetIsExpanded ?? setLocalIsExpanded;
    const { selectCardViewType } = useBoardController();
    const shouldHideForCardSelection = !!selectCardViewType;

    useLayoutEffect(() => {
        const content = contentRef.current;
        if (!content || !projectUID || !cardUID) {
            return;
        }

        if (originRef.current === undefined) {
            originRef.current = takeCardOrigin(projectUID, cardUID);
        }
        const sourceRect = originRef.current;
        const targetRect = content.getBoundingClientRect();
        if (sourceRect && targetRect.width > 0 && targetRect.height > 0) {
            content.style.setProperty("--card-origin-transform", closedTransform(sourceRect, targetRect));
        }
        content.dataset.cardViewerReady = "true";
    }, [projectUID, cardUID, currentUser]);

    useEffect(
        () => () => {
            if (closeTimerRef.current !== null) {
                window.clearTimeout(closeTimerRef.current);
            }
        },
        []
    );

    const finishClose = () => {
        if (!projectUID || finishedCloseRef.current) {
            return;
        }
        finishedCloseRef.current = true;
        if (closeTimerRef.current !== null) {
            window.clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        navigate({
            pathname: ROUTES.BOARD.MAIN(projectUID),
            search: window.location.search,
        });
    };

    const close = () => {
        if (closingRef.current) {
            return;
        }
        closingRef.current = true;

        if (prefersReducedMotion()) {
            finishClose();
            return;
        }

        const source = document.getElementById(`board-card-${cardUID}`);
        const content = contentRef.current;
        const sourceRect = source?.getBoundingClientRect();
        const targetRect = content?.getBoundingClientRect();
        if (sourceRect && targetRect && sourceRect.width > 0 && targetRect.width > 0 && targetRect.height > 0) {
            content?.style.setProperty("--card-origin-transform", closedTransform(sourceRect, targetRect));
        } else {
            content?.style.removeProperty("--card-origin-transform");
        }
        setIsClosing(true);
        closeTimerRef.current = window.setTimeout(finishClose, CARD_ANIMATION_DURATION_MS + 50);
    };

    const handleCloseRequest = () => {
        // Ignore close request during IME composition to prevent double ESC handling
        if (isComposing) {
            return;
        }

        if (isCardEditingRef.current) {
            const cancelCardEdit = cancelCardEditRef.current;
            if (cancelCardEdit) {
                cancelCardEdit();
                return;
            }

            isCardEditingRef.current = false;
            return;
        }

        close();
    };

    const handleEditModeStateChange = useCallback((isEditing: bool, cancelEdit: (() => void) | null) => {
        isCardEditingRef.current = isEditing;
        cancelCardEditRef.current = cancelEdit;
    }, []);

    // Detect IME composition state to handle Korean input properly
    useEffect(() => {
        const handleCompositionStart = () => setIsComposing(true);
        const handleCompositionEnd = () => setIsComposing(false);

        document.addEventListener("compositionstart", handleCompositionStart);
        document.addEventListener("compositionend", handleCompositionEnd);

        return () => {
            document.removeEventListener("compositionstart", handleCompositionStart);
            document.removeEventListener("compositionend", handleCompositionEnd);
        };
    }, []);

    if (!projectUID || !cardUID) {
        return <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} replace />;
    }

    return (
        <>
            {currentUser && cardUID && (
                <>
                    <Dialog.Root
                        modal={false}
                        open={true}
                        onOpenChange={(isOpen) => {
                            if (!isOpen && !selectCardViewType) {
                                handleCloseRequest();
                            }
                        }}
                    >
                        <Dialog.Content
                            ref={contentRef}
                            data-card-viewer=""
                            data-card-viewer-closing={isClosing ? "true" : undefined}
                            disableMotionAnimation
                            onAnimationEnd={(event) => {
                                if (isClosing && event.target === event.currentTarget && event.animationName === "card-viewer-close") {
                                    finishClose();
                                }
                            }}
                            className={cn(
                                "border-0 p-0 shadow-none",
                                isExpanded &&
                                    (embedded
                                        ? cn(
                                              "pointer-events-auto absolute inset-0 z-[1]",
                                              "h-full w-full max-w-none overflow-hidden",
                                              "rounded-none bg-background"
                                          )
                                        : cn(
                                              "pointer-events-auto fixed bottom-0 left-0 right-0 top-16",
                                              "w-auto max-w-none overflow-hidden rounded-none bg-background",
                                              "md:left-[var(--board-chat-sidebar-width,0px)]"
                                          )),
                                !isExpanded &&
                                    cn(
                                        "h-[calc(100dvh-theme(spacing.6))] max-h-[calc(100dvh-theme(spacing.6))]",
                                        "w-[calc(100vw-theme(spacing.4))] max-w-[calc(100vw-theme(spacing.4))] overflow-visible bg-transparent",
                                        "sm:h-[calc(100dvh-theme(spacing.8))] sm:max-h-[calc(100dvh-theme(spacing.8))]",
                                        "sm:w-[calc(100vw-theme(spacing.12))] sm:max-w-[calc(100vw-theme(spacing.12))]",
                                        "lg:w-[min(calc(100vw-theme(spacing.12)),theme(screens.xl))]",
                                        "lg:max-w-[min(calc(100vw-theme(spacing.12)),theme(screens.xl))]",
                                        "2xl:w-[min(calc(100vw-theme(spacing.16)),theme(screens.2xl))]",
                                        "2xl:max-w-[min(calc(100vw-theme(spacing.16)),theme(screens.2xl))]"
                                    ),
                                !isExpanded && CARD_WINDOW_HEIGHT_CLASS,
                                shouldHideForCardSelection && "pointer-events-none -z-[9998] opacity-0"
                            )}
                            overlayClassName={
                                shouldHideForCardSelection
                                    ? "!pointer-events-none bg-transparent opacity-0 backdrop-blur-none"
                                    : isExpanded
                                      ? "!pointer-events-none !absolute !inset-0 !z-[1] bg-transparent backdrop-blur-none"
                                      : embedded
                                        ? CARD_WINDOW_EMBEDDED_OVERLAY_CLASS
                                        : CARD_WINDOW_OVERLAY_CLASS
                            }
                            overlayContentClassName={shouldHideForCardSelection || isExpanded ? "pointer-events-none" : undefined}
                            contentWrapperClassName={
                                shouldHideForCardSelection
                                    ? "pointer-events-none"
                                    : cn(
                                          "pointer-events-none [&_[data-dialog-content=true]]:pointer-events-auto",
                                          !isExpanded && "!items-start pb-2 pt-4 sm:pt-6",
                                          !isExpanded && "[&_[data-radix-scroll-area-viewport]>div]:!overflow-visible"
                                      )
                            }
                            viewportClassName={!isExpanded ? "!py-0" : undefined}
                            aria-describedby=""
                            withCloseButton={false}
                            nonModalOverlay
                            disablePortal={embedded}
                            viewportRef={viewportRef}
                            onInteractOutside={(event) => {
                                if (isNotificationInteraction(event.detail.originalEvent.target)) {
                                    event.preventDefault();
                                    return;
                                }
                                if (isCardEditingRef.current) {
                                    event.preventDefault();
                                    handleCloseRequest();
                                    return;
                                }

                                if (isExpanded) {
                                    event.preventDefault();
                                }
                            }}
                            onOverlayInteract={(event) => {
                                if (isNotificationInteraction(event.target)) {
                                    event.preventDefault();
                                    return;
                                }
                                if (isCardEditingRef.current) {
                                    event.preventDefault();
                                    event.stopPropagation();
                                    handleCloseRequest();
                                    return;
                                }

                                if (isExpanded) {
                                    event.preventDefault();
                                    return;
                                }

                                if (getEditorStore().isInCurrentEditor()) {
                                    event.preventDefault();
                                    event.stopPropagation();

                                    getEditorStore().setCurrentEditor(null);
                                }
                            }}
                        >
                            <BoardCard
                                projectUID={projectUID}
                                cardUID={cardUID}
                                currentUser={currentUser}
                                viewportRef={viewportRef}
                                isExpanded={isExpanded}
                                setIsExpanded={setIsExpanded}
                                onClose={handleCloseRequest}
                                onEditModeStateChange={handleEditModeStateChange}
                            />
                        </Dialog.Content>
                    </Dialog.Root>
                </>
            )}
        </>
    );
};

const BoardCardPage = memo((props: IBoardCardPageProps) => {
    return (
        <BoardCardSectionSaveProvider>
            <BoardCardPageComponent {...props} />
        </BoardCardSectionSaveProvider>
    );
});

export default BoardCardPage;
