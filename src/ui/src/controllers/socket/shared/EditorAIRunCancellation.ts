import type { ISocketContext } from "@/core/providers/SocketProvider";
import { EInternalBotRunStatus } from "@/core/constants/InternalBotRun";
import { ESocketTopic } from "@langboard/core/enums";
import { SocketEvents } from "@langboard/core/constants";

interface IEditorRunCancellation {
    socket: ISocketContext;
    eventKey: string;
    events: { abort: string; status: string; statusResult: string };
    projectUID: string;
    kind: "editor_chat" | "editor_copilot";
    onConfirmed: (taskID: string) => void;
}

const STORAGE_PREFIX = "langboard:editor-ai-cancel:";
const RETRY_INTERVAL_MS = 1_000;
const MAX_ATTEMPTS = 120;
const activeCancellations = new Map<string, () => void>();
const getStoragePrefix = (eventKey: string) => `${STORAGE_PREFIX}${encodeURIComponent(eventKey)}:`;
const getStorageKey = (eventKey: string, taskID: string) => `${getStoragePrefix(eventKey)}${taskID}`;

export const isEditorRunCancellationPending = (eventKey: string, taskID: string): boolean => {
    const key = getStorageKey(eventKey, taskID);
    if (activeCancellations.has(key)) {
        return true;
    }
    try {
        return window.sessionStorage.getItem(key) === taskID;
    } catch {
        return false;
    }
};

export const cancelEditorRun = (props: IEditorRunCancellation, taskID: string): (() => void) => {
    const { socket, eventKey, events, projectUID, kind, onConfirmed } = props;
    const key = getStorageKey(eventKey, taskID);
    if (activeCancellations.has(key)) {
        return () => {};
    }
    try {
        window.sessionStorage.setItem(key, taskID);
    } catch {
        // Cancellation still runs when browser storage is unavailable.
    }

    let attempts = 0;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const clearTimer = () => {
        if (timer !== undefined) {
            clearTimeout(timer);
            timer = undefined;
        }
    };
    const stop = () => {
        if (stopped) {
            return;
        }
        stopped = true;
        clearTimer();
        socket.off({ topic: ESocketTopic.None, event: events.statusResult, eventKey: key, callback: statusReceived });
        socket.off({ topic: ESocketTopic.Global, event: SocketEvents.SERVER.GLOBALS.TASK_ABORTED, eventKey: key, callback: taskAborted });
        socket.off({ event: "open", eventKey: key, callback: requestCancellation });
        activeCancellations.delete(key);
    };
    const statusReceived = (data: Record<string, unknown>) => {
        if (stopped || data.task_id !== taskID) {
            return;
        }
        if (
            data.status !== EInternalBotRunStatus.Completed &&
            data.status !== EInternalBotRunStatus.Failed &&
            data.status !== EInternalBotRunStatus.Cancelled &&
            data.status !== EInternalBotRunStatus.Uncertain
        ) {
            return;
        }

        stop();
        try {
            window.sessionStorage.removeItem(key);
        } catch {
            // Server confirmation is authoritative even if storage is unavailable.
        }
        onConfirmed(taskID);
    };
    const taskAborted = (data: { task_id: string }) => {
        statusReceived({ task_id: data.task_id, status: EInternalBotRunStatus.Cancelled });
    };
    const requestCancellation = () => {
        if (stopped) {
            return;
        }
        clearTimer();
        if (attempts >= MAX_ATTEMPTS) {
            stop();
            return;
        }
        attempts += 1;
        const sent = socket.send({
            topic: ESocketTopic.None,
            eventName: events.abort,
            data: { task_id: taskID, project_uid: projectUID },
        });
        if (sent.isConnected) {
            socket.send({
                topic: ESocketTopic.None,
                eventName: events.status,
                data: { task_id: taskID, project_uid: projectUID, kind },
            });
        }
        if (!stopped) {
            timer = setTimeout(requestCancellation, RETRY_INTERVAL_MS);
        }
    };

    activeCancellations.set(key, stop);
    socket.on({ topic: ESocketTopic.None, event: events.statusResult, eventKey: key, callback: statusReceived });
    socket.on({ topic: ESocketTopic.Global, event: SocketEvents.SERVER.GLOBALS.TASK_ABORTED, eventKey: key, callback: taskAborted });
    socket.on({ event: "open", eventKey: key, callback: requestCancellation });
    requestCancellation();
    return stop;
};

export const resumeEditorRunCancellations = (props: IEditorRunCancellation): (() => void) => {
    const tasks: string[] = [];
    try {
        const storage = window.sessionStorage;
        const prefix = getStoragePrefix(props.eventKey);
        for (let index = 0; index < storage.length; index++) {
            const key = storage.key(index);
            const taskID = key?.startsWith(prefix) ? storage.getItem(key) : null;
            if (taskID && /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(taskID)) {
                tasks.push(taskID);
            }
        }
    } catch {
        return () => {};
    }
    const cleanups = tasks.map((taskID) => cancelEditorRun(props, taskID));
    return () => cleanups.forEach((cleanup) => cleanup());
};
