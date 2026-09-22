import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

interface IBoardChatStore {
    currentSessionUIDMap: Record<string, string | undefined>;
    chatVisibleMap: Record<string, bool>;
    getCurrentSessionUID: (projectUID: string) => string | undefined;
    setCurrentSessionUID: (projectUID: string, sessionUID: string | undefined) => void;
    getPendingTask: (userUID: string, projectUID: string) => { taskId: string; createdAt: number } | null;
    setPendingTaskId: (userUID: string, projectUID: string, taskId: string | null) => void;
    isChatHidden: (projectUID: string) => bool;
    setChatVisible: (projectUID: string, visible: bool) => void;
}

const getCurrentSessionStorageKey = (projectUID: string) => `board:${projectUID}:chat:current-session`;
const getChatVisibleStorageKey = (projectUID: string) => `board:${projectUID}:chat-visible`;
const getPendingTaskStorageKey = (userUID: string, projectUID: string) => `board:${userUID}:${projectUID}:chat:pending-task`;

const getStoredCurrentSessionUID = (projectUID: string): string | undefined => {
    return localStorage.getItem(getCurrentSessionStorageKey(projectUID)) ?? undefined;
};

const getStoredChatVisible = (projectUID: string): bool => {
    return localStorage.getItem(getChatVisibleStorageKey(projectUID)) === "true";
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
        getPendingTask: (userUID, projectUID) => {
            const key = getPendingTaskStorageKey(userUID, projectUID);
            const value = sessionStorage.getItem(key);
            if (!value) {
                return null;
            }

            try {
                const task: unknown = JSON.parse(value);
                if (
                    task &&
                    typeof task === "object" &&
                    "taskId" in task &&
                    typeof task.taskId === "string" &&
                    task.taskId.length > 0 &&
                    "createdAt" in task &&
                    typeof task.createdAt === "number" &&
                    Number.isFinite(task.createdAt) &&
                    task.createdAt > 0
                ) {
                    return { taskId: task.taskId, createdAt: task.createdAt };
                }

                sessionStorage.removeItem(key);
                return null;
            } catch {
                // Previous versions stored the task ID directly.
            }

            const legacyTask = { taskId: value, createdAt: Date.now() };
            sessionStorage.setItem(key, JSON.stringify(legacyTask));
            return legacyTask;
        },
        setPendingTaskId: (userUID, projectUID, taskId) => {
            const key = getPendingTaskStorageKey(userUID, projectUID);
            if (taskId) {
                sessionStorage.setItem(key, JSON.stringify({ taskId, createdAt: Date.now() }));
            } else {
                sessionStorage.removeItem(key);
            }
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
