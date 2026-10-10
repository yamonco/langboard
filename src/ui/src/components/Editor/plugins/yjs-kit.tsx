import { YjsPlugin } from "@platejs/yjs/react";
import { RemoteCursorOverlay } from "@/components/plate-ui/remote-cursor-overlay";
import { ISocketContext } from "@/core/providers/SocketProvider";
import { Utils } from "@langboard/core/utils";

export interface ICreateYjsKit {
    socket: ISocketContext;
    userName: string;
    documentID: string;
    onSyncChange?: (isSynced: bool) => void;
}

export const createYjsKit = ({ socket, userName, documentID, onSyncChange }: ICreateYjsKit) => {
    const url = socket.getAuthorizedWebSocketUrl("editor-sync");
    if (!url) {
        return null;
    }

    return YjsPlugin.configure({
        render: {
            afterEditable: RemoteCursorOverlay,
        },
        options: {
            cursors: {
                autoSend: false,
                data: {
                    name: userName,
                    color: new Utils.Color.Generator(userName).generateRandomColor(),
                },
            },
            providers: [
                {
                    type: "hocuspocus",
                    options: {
                        name: documentID,
                        url,
                    },
                },
            ],
            onDisconnect: () => onSyncChange?.(false),
            onError: () => onSyncChange?.(false),
            onSyncChange: ({ isSynced }) => onSyncChange?.(isSynced),
        },
    });
};
