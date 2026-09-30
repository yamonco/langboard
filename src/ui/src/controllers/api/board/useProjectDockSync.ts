import { useEffect } from "react";
import { ESocketTopic } from "@langboard/core/enums";
import { useSocket } from "@/core/providers/SocketProvider";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import refreshProjectColumnDock from "@/controllers/api/board/refreshProjectColumnDock";

export default function useProjectDockSync(projectUID: string) {
    const socket = useSocket();
    useEffect(() => {
        let alive = true;
        let subscribed = false;
        let hasSubscribed = false;
        const refresh = () => {
            void refreshProjectColumnDock(projectUID).catch((error) => {
                if (alive) setupApiErrorHandler({}).handle(error);
            });
        };
        const key = `project-dock-sync-${projectUID}`;
        socket.subscribeTopicNotifier({
            topic: ESocketTopic.Board,
            topicId: projectUID,
            key,
            notifier: (topicID, isSubscribed) => {
                if (topicID !== projectUID || !alive) return;
                if (isSubscribed && !subscribed && hasSubscribed) refresh();
                if (isSubscribed) hasSubscribed = true;
                subscribed = isSubscribed;
            },
        });
        return () => {
            alive = false;
            socket.unsubscribeTopicNotifier({ topic: ESocketTopic.Board, topicId: projectUID, key });
        };
    }, [projectUID, socket]);
}
