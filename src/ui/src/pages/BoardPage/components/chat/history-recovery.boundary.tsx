import { useRef, useState } from "react";
import { session, rows } from "./history-recovery.state";
let calls = 0;
let rejectOld: (() => void) | undefined;
export function useBoardChat() {
    return { projectUID: "fixture", currentSessionUID: session, scrollToBottomRef: useRef(() => {}), isAtBottomRef: useRef(true) };
}
export const ChatMessageModel = { Model: { useModels: (predicate: (row: (typeof rows)[number]) => boolean) => rows.filter(predicate) } };
export function ChatMessage({ chatMessage }: { chatMessage: (typeof rows)[number] }) {
    return <p>{chatMessage.uid}</p>;
}
export function useHistory() {
    const [isLastPage, setIsLastPage] = useState(true);
    const pageRef = useRef(0),
        lastCurrentDateRef = useRef(new Date()),
        lastPagesRef = useRef<Record<string, number>>({});
    const mutateAsync = async () => {
        calls++;
        if (location.search.includes("stale") && session === "a")
            return new Promise<void>((_, reject) => {
                rejectOld = () => reject(Error("offline"));
            });
        if (!location.search.includes("stale") && calls === 1) throw Error("offline");
    };
    return { mutateAsync, isLastPage, setIsLastPage, pageRef, lastCurrentDateRef, lastPagesRef };
}
export function rejectStale() {
    rejectOld?.();
}
