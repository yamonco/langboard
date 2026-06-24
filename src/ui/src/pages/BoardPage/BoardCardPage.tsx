import Dialog from "@/components/base/Dialog";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { useAuth } from "@/core/providers/AuthProvider";
import { ROUTES } from "@/core/routing/constants";
import { getEditorStore } from "@/core/stores/EditorStore";
import { cn } from "@/core/utils/ComponentUtils";
import BoardCard from "@/pages/BoardPage/components/card/BoardCard";
import { BoardCardSectionSaveProvider } from "@/pages/BoardPage/components/card/BoardCardSectionSaveProvider";
import { EHttpStatus } from "@langboard/core/enums";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import { Navigate, useParams } from "react-router";
import { useBoardController } from "@/core/providers/BoardController";

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
    const isCardEditingRef = useRef(false);
    const cancelCardEditRef = useRef<(() => void) | null>(null);
    const [isComposing, setIsComposing] = useState(false);
    const [localIsExpanded, setLocalIsExpanded] = useState(false);
    const isExpanded = controlledIsExpanded ?? localIsExpanded;
    const setIsExpanded = controlledSetIsExpanded ?? setLocalIsExpanded;
    const { selectCardViewType } = useBoardController();
    const shouldHideForCardSelection = !!selectCardViewType;

    if (!projectUID || !cardUID) {
        return <Navigate to={ROUTES.ERROR(EHttpStatus.HTTP_404_NOT_FOUND)} replace />;
    }

    const close = () => {
        navigate({
            pathname: ROUTES.BOARD.MAIN(projectUID),
            search: window.location.search,
        });
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
                                shouldHideForCardSelection && "pointer-events-none -z-[9998] opacity-0"
                            )}
                            overlayClassName={
                                shouldHideForCardSelection
                                    ? "!pointer-events-none bg-transparent opacity-0 backdrop-blur-none"
                                    : isExpanded
                                      ? "!pointer-events-none !absolute !inset-0 !z-[1] bg-transparent backdrop-blur-none"
                                      : undefined
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
