import { TDashboardStyledLayoutProps } from "@/components/Layout/DashboardStyledLayout";
import { useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import { InternalBotModel, ProjectCardRelationship } from "@/core/models";
import { useAuth } from "@/core/providers/AuthProvider";
import { BoardChatProvider } from "@/core/providers/BoardChatProvider";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { Utils } from "@langboard/core/utils";
import { createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

export type TBoardViewType = "board" | "card" | "graph" | "wiki" | "settings";

interface IStartCardSelectionProps {
    type: ProjectCardRelationship.TRelationship;
    currentUID: string;
    initialSelections?: [string, string][];
    saveCallback: (relationships: [string, string][]) => void;
    cancelCallback: () => void;
}

interface IRelationshipSelectionSyncState {
    section: string;
    uid: string;
}

export interface IRelationshipSelectionActor {
    color: string;
    name: string;
    updatedAt: number;
    userID?: string;
}

interface IRelationshipSelectionDraftEntry {
    actor?: IRelationshipSelectionActor;
    cardUID: string;
    relationshipUID: string;
}

interface IRelationshipSelectionDraft {
    selections: [string, string][];
    selectionActors: Record<string, IRelationshipSelectionActor>;
}

interface IBoardChatState {
    bot: InternalBotModel.TModel;
    projectUID: string;
}

export interface IBoardControllerContext {
    boardViewType: TBoardViewType;
    selectCardViewType?: ProjectCardRelationship.TRelationship;
    selectedRelationshipUIDs: [string, string][];
    currentCardUIDRef: React.RefObject<string | null>;
    disabledCardSelectionUIDsRef: React.RefObject<string[]>;
    chatResizableSidebar: TDashboardStyledLayoutProps["resizableSidebar"];
    chatSidebarRef: React.RefObject<HTMLDivElement | null>;
    boardChat?: IBoardChatState;
    setBoardViewType: React.Dispatch<React.SetStateAction<TBoardViewType>>;
    startCardSelection: (props: IStartCardSelectionProps) => void;
    setSelectedRelationshipCardUIDs: React.Dispatch<React.SetStateAction<[string, string][]>>;
    setCardSelection: (cardUID: string, relationshipUID?: string) => void;
    saveCardSelection: () => void;
    cancelCardSelection: () => void;
    getRelationshipSelectionActor: (cardUID: string) => IRelationshipSelectionActor | undefined;
    isSelectedCard: (cardUID: string) => bool;
    isDisabledCard: (cardUID: string) => bool;
    filterRelationships: (cardUID: string, relationships: ProjectCardRelationship.TModel[], isParent: bool) => ProjectCardRelationship.TModel[];
    filterRelatedCardUIDs: (cardUID: string, relationships: ProjectCardRelationship.TModel[], isParent: bool) => string[];
    setChatResizableSidebar: React.Dispatch<React.SetStateAction<TDashboardStyledLayoutProps["resizableSidebar"]>>;
    setBoardChat: React.Dispatch<React.SetStateAction<IBoardChatState | undefined>>;
}

interface IBoardControllerProps {
    children: React.ReactNode;
}

const initialContext = {
    boardViewType: "board" as const,
    selectedRelationshipUIDs: [],
    currentCardUIDRef: { current: null },
    disabledCardSelectionUIDsRef: { current: [] },
    chatResizableSidebar: undefined,
    chatSidebarRef: { current: null },
    boardChat: undefined,
    setBoardViewType: () => {},
    startCardSelection: () => {},
    setSelectedRelationshipCardUIDs: () => {},
    setCardSelection: () => {},
    saveCardSelection: () => {},
    cancelCardSelection: () => {},
    getRelationshipSelectionActor: () => undefined,
    isSelectedCard: () => false,
    isDisabledCard: () => false,
    filterRelationships: () => [],
    filterRelatedCardUIDs: () => [],
    setChatResizableSidebar: () => {},
    setBoardChat: () => {},
};

const BoardControllerContext = createContext<IBoardControllerContext>(initialContext);

const isRelationshipSelectionTuple = (value: unknown): value is [string, string] => {
    return Array.isArray(value) && value.length === 2 && Utils.Type.isString(value[0]) && Utils.Type.isString(value[1]);
};

const isRelationshipSelectionDraftEntry = (value: unknown): value is IRelationshipSelectionDraftEntry => {
    if (!Utils.Type.isObject(value)) {
        return false;
    }

    const entry = value as Record<string, unknown>;
    return Utils.Type.isString(entry.cardUID) && Utils.Type.isString(entry.relationshipUID);
};

const serializeRelationshipSelections = (selections: [string, string][], selectionActors: Record<string, IRelationshipSelectionActor>) =>
    JSON.stringify({
        selections: selections.map(([cardUID, relationshipUID]) => ({
            actor: selectionActors[cardUID],
            cardUID,
            relationshipUID,
        })),
        updatedAt: Date.now(),
    });

const parseRelationshipSelections = (value: string): IRelationshipSelectionDraft | null => {
    try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) {
            return parsed.every(isRelationshipSelectionTuple) ? { selectionActors: {}, selections: parsed } : null;
        }

        if (!Utils.Type.isArray(parsed?.selections)) {
            return null;
        }

        if (parsed.selections.every(isRelationshipSelectionTuple)) {
            return {
                selectionActors: {},
                selections: parsed.selections,
            };
        }

        if (!parsed.selections.every(isRelationshipSelectionDraftEntry)) {
            return null;
        }

        const selectionActors: Record<string, IRelationshipSelectionActor> = {};
        const selections = (parsed.selections as IRelationshipSelectionDraftEntry[]).map((selection) => {
            if (selection.actor) {
                selectionActors[selection.cardUID] = selection.actor;
            }

            return [selection.cardUID, selection.relationshipUID] satisfies [string, string];
        });

        return {
            selectionActors,
            selections,
        };
    } catch {
        return null;
    }
};

export const BoardController = memo(({ children }: IBoardControllerProps): React.ReactNode => {
    const { currentUser } = useAuth();
    const [boardViewType, setBoardViewType] = useState<TBoardViewType>("board");
    const [selectCardViewType, setSelectCardViewType] = useState<ProjectCardRelationship.TRelationship>();
    const [selectedRelationshipUIDs, setSelectedRelationshipCardUIDs] = useState<[string, string][]>([]);
    const selectedRelationshipUIDsRef = useRef<[string, string][]>([]);
    const [relationshipSelectionActors, setRelationshipSelectionActors] = useState<Record<string, IRelationshipSelectionActor>>({});
    const relationshipSelectionActorsRef = useRef<Record<string, IRelationshipSelectionActor>>({});
    const [relationshipSelectionSyncState, setRelationshipSelectionSyncState] = useState<IRelationshipSelectionSyncState>();
    const [chatResizableSidebar, setChatResizableSidebar] = useState<TDashboardStyledLayoutProps["resizableSidebar"]>();
    const [boardChat, setBoardChat] = useState<IBoardChatState>();
    const currentCardUIDRef = useRef<string>(null);
    const saveCardSelectionCallbackRef = useRef<(relationships: [string, string][]) => void>(null);
    const disabledCardSelectionUIDsRef = useRef<string[]>([]);
    const cancelCardSelectionCallbackRef = useRef<() => void>(null);
    const chatSidebarRef = useRef<HTMLDivElement>(null);
    const currentUserName = useMemo(() => {
        if (!currentUser) {
            return "";
        }

        return `${currentUser.firstname} ${currentUser.lastname}`.trim() || currentUser.username;
    }, [currentUser]);
    const currentUserColor = useMemo(() => new Utils.Color.Generator(currentUserName || "Anonymous").generateRandomColor(), [currentUserName]);
    const currentRelationshipSelectionActor = useMemo<IRelationshipSelectionActor>(
        () => ({
            color: currentUserColor,
            name: currentUserName,
            updatedAt: Date.now(),
            userID: currentUser?.uid,
        }),
        [currentUser, currentUserColor, currentUserName]
    );
    const selectedRelationshipValue = useMemo(
        () => serializeRelationshipSelections(selectedRelationshipUIDs, relationshipSelectionActors),
        [relationshipSelectionActors, selectedRelationshipUIDs]
    );
    const handleRelationshipSelectionValueChange = useCallback((value: string) => {
        const draft = parseRelationshipSelections(value);
        if (!draft) {
            return;
        }

        if (
            JSON.stringify(selectedRelationshipUIDsRef.current) === JSON.stringify(draft.selections) &&
            JSON.stringify(relationshipSelectionActorsRef.current) === JSON.stringify(draft.selectionActors)
        ) {
            return;
        }

        selectedRelationshipUIDsRef.current = draft.selections;
        relationshipSelectionActorsRef.current = draft.selectionActors;
        setSelectedRelationshipCardUIDs(draft.selections);
        setRelationshipSelectionActors(draft.selectionActors);
    }, []);
    const { isSynced: isRelationshipSelectionSynced, updateValue: updateRelationshipSelectionValue } = useCollaborativeText({
        defaultValue: selectedRelationshipValue,
        disabled: !relationshipSelectionSyncState,
        collaborationType: EEditorCollaborationType.Card,
        uid: relationshipSelectionSyncState?.uid ?? "relationship-selection-idle",
        section: relationshipSelectionSyncState?.section,
        field: "selected-relationships",
        resetSyncedValueToDefault: true,
        onValueChange: handleRelationshipSelectionValueChange,
    });

    useEffect(() => {
        selectedRelationshipUIDsRef.current = selectedRelationshipUIDs;
    }, [selectedRelationshipUIDs]);

    useEffect(() => {
        relationshipSelectionActorsRef.current = relationshipSelectionActors;
    }, [relationshipSelectionActors]);

    useEffect(() => {
        if (!relationshipSelectionSyncState || !isRelationshipSelectionSynced) {
            return;
        }

        updateRelationshipSelectionValue(selectedRelationshipValue);
    }, [isRelationshipSelectionSynced, relationshipSelectionSyncState, selectedRelationshipValue, updateRelationshipSelectionValue]);

    const setCardSelection = (cardUID: string, relationshipUID?: string) => {
        if (!relationshipUID) {
            const nextSelections = selectedRelationshipUIDsRef.current.filter(([selectedCardUID]) => selectedCardUID !== cardUID);
            const nextSelectionActors = { ...relationshipSelectionActorsRef.current };
            delete nextSelectionActors[cardUID];

            selectedRelationshipUIDsRef.current = nextSelections;
            relationshipSelectionActorsRef.current = nextSelectionActors;
            setSelectedRelationshipCardUIDs(nextSelections);
            setRelationshipSelectionActors(nextSelectionActors);
            return;
        }

        const existedSelectionIndex = selectedRelationshipUIDsRef.current.findIndex(([selectedCardUID]) => selectedCardUID === cardUID);
        const nextSelections =
            existedSelectionIndex < 0
                ? [...selectedRelationshipUIDsRef.current, [cardUID, relationshipUID] satisfies [string, string]]
                : selectedRelationshipUIDsRef.current.map((selection, index) =>
                      index === existedSelectionIndex ? ([cardUID, relationshipUID] satisfies [string, string]) : selection
                  );
        const nextSelectionActors = {
            ...relationshipSelectionActorsRef.current,
            [cardUID]: {
                ...currentRelationshipSelectionActor,
                updatedAt: Date.now(),
            },
        };

        selectedRelationshipUIDsRef.current = nextSelections;
        relationshipSelectionActorsRef.current = nextSelectionActors;
        setSelectedRelationshipCardUIDs(nextSelections);
        setRelationshipSelectionActors(nextSelectionActors);
    };

    const startCardSelection = ({ type, currentUID, initialSelections = [], saveCallback, cancelCallback }: IStartCardSelectionProps) => {
        currentCardUIDRef.current = currentUID;
        saveCardSelectionCallbackRef.current = saveCallback;
        cancelCardSelectionCallbackRef.current = cancelCallback;
        selectedRelationshipUIDsRef.current = initialSelections;
        relationshipSelectionActorsRef.current = {};
        setSelectedRelationshipCardUIDs(initialSelections);
        setRelationshipSelectionActors({});
        setRelationshipSelectionSyncState({
            uid: currentUID,
            section: `relationships-${type}`,
        });
        setSelectCardViewType(type);
    };

    const saveCardSelection = () => {
        const selections = [...selectedRelationshipUIDsRef.current];
        setSelectCardViewType(undefined);
        setRelationshipSelectionSyncState(undefined);
        selectedRelationshipUIDsRef.current = [];
        relationshipSelectionActorsRef.current = {};
        setSelectedRelationshipCardUIDs([]);
        setRelationshipSelectionActors({});
        setTimeout(() => {
            saveCardSelectionCallbackRef.current?.(selections);
            clear();
        }, 0);
    };

    const cancelCardSelection = () => {
        setSelectCardViewType(undefined);
        setRelationshipSelectionSyncState(undefined);
        selectedRelationshipUIDsRef.current = [];
        relationshipSelectionActorsRef.current = {};
        setSelectedRelationshipCardUIDs([]);
        setRelationshipSelectionActors({});
        setTimeout(() => {
            cancelCardSelectionCallbackRef.current?.();
            clear();
        }, 0);
    };

    const isSelectedCard = (cardUID: string) => selectedRelationshipUIDs.some(([selectedCardUID]) => selectedCardUID === cardUID);
    const getRelationshipSelectionActor = (cardUID: string) => relationshipSelectionActors[cardUID];
    const isDisabledCard = (cardUID: string) => disabledCardSelectionUIDsRef.current.includes(cardUID);

    const filterRelationships = (cardUID: string, relationships: ProjectCardRelationship.TModel[], isParent: bool) => {
        return relationships.filter((relationship) => (isParent ? relationship.child_card_uid : relationship.parent_card_uid) === cardUID);
    };

    const filterRelatedCardUIDs = (cardUID: string, relationships: ProjectCardRelationship.TModel[], isParent: bool) => {
        return filterRelationships(cardUID, relationships, isParent).map((relationship) =>
            isParent ? relationship.parent_card_uid : relationship.child_card_uid
        );
    };

    const clear = () => {
        saveCardSelectionCallbackRef.current = null;
        cancelCardSelectionCallbackRef.current = null;
        currentCardUIDRef.current = null;
        disabledCardSelectionUIDsRef.current = [];
        setRelationshipSelectionSyncState(undefined);
    };

    const content = (
        <BoardControllerContext.Provider
            value={{
                boardViewType,
                selectCardViewType,
                selectedRelationshipUIDs,
                currentCardUIDRef,
                disabledCardSelectionUIDsRef,
                chatResizableSidebar,
                chatSidebarRef,
                boardChat,
                setBoardViewType,
                startCardSelection,
                setSelectedRelationshipCardUIDs,
                setCardSelection,
                saveCardSelection,
                cancelCardSelection,
                getRelationshipSelectionActor,
                isSelectedCard,
                isDisabledCard,
                filterRelationships,
                filterRelatedCardUIDs,
                setChatResizableSidebar,
                setBoardChat,
            }}
        >
            {children}
        </BoardControllerContext.Provider>
    );

    if (!boardChat) {
        return content;
    }

    return (
        <BoardChatProvider projectUID={boardChat.projectUID} bot={boardChat.bot}>
            {content}
        </BoardChatProvider>
    );
});

export const useBoardController = () => {
    const context = useContext(BoardControllerContext);
    if (!context) {
        throw new Error("useBoardController must be used within a BoardController");
    }
    return context;
};
