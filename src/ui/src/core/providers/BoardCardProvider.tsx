import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AuthUser, ProjectCard } from "@/core/models";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { ISocketContext, useSocket } from "@/core/providers/SocketProvider";
import { TUserLikeModel } from "@/core/models/ModelRegistry";
import { ProjectRole } from "@/core/models/roles";
import { Utils } from "@langboard/core/utils";

// Must stay aligned with Tailwind `md` breakpoint in `tailwind.config.js` (768px).
const DESKTOP_COMMENT_BREAKPOINT = 768;

export interface IBoardCardContext {
    projectUID: string;
    card: ProjectCard.TModel;
    currentUser: AuthUser.TModel;
    viewportRef: React.RefObject<HTMLDivElement | null>;
    hasRoleAction: ReturnType<typeof useRoleActionFilter<ProjectRole.TActions>>["hasRoleAction"];
    canEditCard: bool;
    socket: ISocketContext;
    replyRef: React.RefObject<(target: TUserLikeModel) => void>;
    cardEditMode: "view" | "edit";
    isCardEditing: bool;
    setCardEditMode: React.Dispatch<React.SetStateAction<"view" | "edit">>;
    enterCardEditMode: () => void;
    leaveCardEditMode: () => void;
    toggleCardEditMode: () => void;
    sharedClassNames: {
        popoverContent: string;
    };
}

interface IBoardCardProviderProps {
    projectUID: string;
    card: ProjectCard.TModel;
    currentUser: AuthUser.TModel;
    viewportRef: React.RefObject<HTMLDivElement | null>;
    children: React.ReactNode;
}

const initialContext = {
    projectUID: "",
    card: {} as ProjectCard.TModel,
    currentUser: {} as AuthUser.TModel,
    viewportRef: { current: null },
    hasRoleAction: () => false,
    canEditCard: false,
    socket: {} as ISocketContext,
    replyRef: { current: () => {} },
    cardEditMode: "view" as const,
    isCardEditing: false,
    setCardEditMode: () => "view",
    enterCardEditMode: () => {},
    leaveCardEditMode: () => {},
    toggleCardEditMode: () => {},
    sharedClassNames: {} as IBoardCardContext["sharedClassNames"],
};

const BoardCardContext = createContext<IBoardCardContext>(initialContext);

export interface IBoardCardPanelContext {
    isCommentPanelOpen: bool;
    setIsCommentPanelOpen: React.Dispatch<React.SetStateAction<bool>>;
    toggleCommentPanel: () => void;
    isActionPanelOpen: bool;
    setIsActionPanelOpen: React.Dispatch<React.SetStateAction<bool>>;
    toggleActionPanel: () => void;
    commentLayoutMode: "mobile" | "panel";
}

const initialPanelContext = {
    isCommentPanelOpen: false,
    setIsCommentPanelOpen: () => false,
    toggleCommentPanel: () => {},
    isActionPanelOpen: false,
    setIsActionPanelOpen: () => false,
    toggleActionPanel: () => {},
    commentLayoutMode: "mobile" as const,
};

const BoardCardPanelContext = createContext<IBoardCardPanelContext>(initialPanelContext);

export const BoardCardProvider = ({ projectUID, card, currentUser, viewportRef, children }: IBoardCardProviderProps): React.ReactNode => {
    const socket = useSocket();
    const replyRef = useRef<(target: TUserLikeModel) => void>(() => {});
    const commentCount = card.useField("count_comment");
    const [isCommentPanelOpen, setIsCommentPanelOpen] = useState(() => commentCount > 0);
    const [isActionPanelOpen, setIsActionPanelOpen] = useState(false);
    const [commentLayoutMode, setCommentLayoutMode] = useState<"mobile" | "panel">("mobile");
    const [cardEditMode, setCardEditMode] = useState<"view" | "edit">("view");
    const currentUserRoleActions = card.useField("current_auth_role_actions");
    const { hasRoleAction } = useRoleActionFilter(currentUserRoleActions);
    const canEditCard = hasRoleAction(ProjectRole.EAction.CardUpdate);
    const sharedClassNames = useMemo(
        () => ({
            popoverContent: "w-full max-w-[calc(var(--radix-popper-available-width)_-_theme(spacing.10))]",
        }),
        []
    );

    useEffect(() => {
        if (Utils.Type.isNullOrUndefined(window)) {
            return;
        }

        const mediaQuery = window.matchMedia(`(min-width: ${DESKTOP_COMMENT_BREAKPOINT}px)`);
        const updateLayoutMode = () => {
            setCommentLayoutMode(mediaQuery.matches ? "panel" : "mobile");
        };

        updateLayoutMode();
        mediaQuery.addEventListener("change", updateLayoutMode);

        return () => {
            mediaQuery.removeEventListener("change", updateLayoutMode);
        };
    }, []);

    const toggleCommentPanel = useCallback(() => setIsCommentPanelOpen((prev) => !prev), []);
    const toggleActionPanel = useCallback(() => setIsActionPanelOpen((prev) => !prev), []);
    const enterCardEditMode = useCallback(() => {
        if (!canEditCard) {
            return;
        }

        setCardEditMode("edit");
    }, [canEditCard]);
    const leaveCardEditMode = useCallback(() => {
        setCardEditMode("view");
    }, []);
    const toggleCardEditMode = useCallback(() => {
        if (!canEditCard) {
            return;
        }

        setCardEditMode((prev) => (prev === "edit" ? "view" : "edit"));
    }, [canEditCard]);

    const contextValue = useMemo(
        () => ({
            projectUID,
            card,
            currentUser,
            viewportRef,
            hasRoleAction,
            canEditCard,
            socket,
            replyRef,
            cardEditMode,
            isCardEditing: cardEditMode === "edit",
            setCardEditMode,
            enterCardEditMode,
            leaveCardEditMode,
            toggleCardEditMode,
            sharedClassNames,
        }),
        [
            projectUID,
            card,
            currentUser,
            viewportRef,
            hasRoleAction,
            canEditCard,
            socket,
            cardEditMode,
            enterCardEditMode,
            leaveCardEditMode,
            toggleCardEditMode,
            sharedClassNames,
        ]
    );
    const panelContextValue = useMemo(
        () => ({
            isCommentPanelOpen,
            setIsCommentPanelOpen,
            toggleCommentPanel,
            isActionPanelOpen,
            setIsActionPanelOpen,
            toggleActionPanel,
            commentLayoutMode,
        }),
        [isCommentPanelOpen, toggleCommentPanel, isActionPanelOpen, toggleActionPanel, commentLayoutMode]
    );

    return (
        <BoardCardContext.Provider value={contextValue}>
            <BoardCardPanelContext.Provider value={panelContextValue}>{children}</BoardCardPanelContext.Provider>
        </BoardCardContext.Provider>
    );
};

export const useBoardCard = () => {
    const context = useContext(BoardCardContext);
    if (!context) {
        throw new Error("useBoardCard must be used within a BoardCardProvider");
    }
    return context;
};

export const useBoardCardPanel = () => {
    const context = useContext(BoardCardPanelContext);
    if (!context) {
        throw new Error("useBoardCardPanel must be used within a BoardCardProvider");
    }
    return context;
};
