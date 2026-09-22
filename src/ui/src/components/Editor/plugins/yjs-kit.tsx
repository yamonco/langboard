import { YjsPlugin } from "@platejs/yjs/react";
import { HocuspocusProviderWrapper } from "@platejs/yjs";
import { MarkdownPlugin } from "@platejs/markdown";
import { prepareRichDraftPatch } from "@/components/Editor/prepareRichDraftPatch";
import { RemoteCursorOverlay } from "@/components/plate-ui/remote-cursor-overlay";
import { ISocketContext } from "@/core/providers/SocketProvider";
import { Utils } from "@langboard/core/utils";

export interface ICreateYjsKit {
    socket: ISocketContext;
    userName: string;
    documentID: string;
    onSyncChange?: (isSynced: bool) => void;
}

export const createYjsKit = ({ socket, userName, documentID, onSyncChange }: ICreateYjsKit): ReturnType<typeof YjsPlugin.configure> | null => {
    const url = socket.getAuthorizedWebSocketUrl("editor-sync");
    if (!url) {
        return null;
    }

    return YjsPlugin.configure(({ editor, getOptions }) => ({
        render: {
            afterEditable: RemoteCursorOverlay,
        },
        options: {
            cursors: {
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
                        onStateless: ({ payload }) => {
                            const response = prepareRichDraftPatch(payload, (markdown) =>
                                editor.getApi(MarkdownPlugin).markdown.deserialize(markdown)
                            );
                            if (!response) {
                                return;
                            }
                            const provider = getOptions()._providers.find((item) => item instanceof HocuspocusProviderWrapper);
                            if (provider instanceof HocuspocusProviderWrapper) {
                                provider.provider.sendStateless(response);
                            }
                        },
                    },
                },
            ],
            onDisconnect: () => onSyncChange?.(false),
            onError: () => onSyncChange?.(false),
            onSyncChange: ({ isSynced }) => onSyncChange?.(isSynced),
        },
    }));
};
