import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

interface IBoardChatStore {
    currentSessionUIDMap: Record<string, string | undefined>;
    chatVisibleMap: Record<string, bool>;
    getCurrentSessionUID: (projectUID: string) => string | undefined;
    setCurrentSessionUID: (projectUID: string, sessionUID: string | undefined) => void;
    isChatHidden: (projectUID: string) => bool;
    setChatVisible: (projectUID: string, visible: bool) => void;
}

const getCurrentSessionStorageKey = (projectUID: string) => `board:${projectUID}:chat:current-session`;
const getChatVisibleStorageKey = (projectUID: string) => `board:${projectUID}:chat-visible`;

const getStoredCurrentSessionUID = (projectUID: string): string | undefined => {
    return localStorage.getItem(getCurrentSessionStorageKey(projectUID)) ?? undefined;
};

const getStoredChatVisible = (projectUID: string): bool => {
    return localStorage.getItem(getChatVisibleStorageKey(projectUID)) !== "false";
};

const useBoardChatStore = create(
    immer<IBoardChatStore>((set, get) => ({
        currentSessionUIDMap: {},
        chatVisibleMap: {},
        getCurrentSessionUID: (projectUID) => {
            if (projectUID in get().currentSessionUIDMap) {
                return get().currentSessionUIDMap[projectUID];
            }
            return getStoredCurrentSessionUID(projectUID);
        },
        setCurrentSessionUID: (projectUID, sessionUID) => {
            set((state) => {
                state.currentSessionUIDMap[projectUID] = sessionUID;
            });

            if (sessionUID) {
                localStorage.setItem(getCurrentSessionStorageKey(projectUID), sessionUID);
                return;
            }

            localStorage.removeItem(getCurrentSessionStorageKey(projectUID));
        },
        isChatHidden: (projectUID) => {
            if (projectUID in get().chatVisibleMap) {
                return !get().chatVisibleMap[projectUID];
            }
            return !getStoredChatVisible(projectUID);
        },
        setChatVisible: (projectUID, visible) => {
            set((state) => {
                state.chatVisibleMap[projectUID] = visible;
            });
            localStorage.setItem(getChatVisibleStorageKey(projectUID), visible ? "true" : "false");
        },
    }))
);

export const getBoardChatStore = () => useBoardChatStore.getState();

export default useBoardChatStore;
