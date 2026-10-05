import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { ChatMessageModel, ChatSessionModel, InternalBotModel } from "@/core/models";
import { ISocketContext, useSocket } from "@/core/providers/SocketProvider";
import useBoardChatSentHandlers from "@/controllers/socket/board/chat/useBoardChatSentHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { useTranslation } from "react-i18next";
import Toast from "@/components/base/Toast";
import useBoardChatStreamHandlers from "@/controllers/socket/board/chat/useBoardChatStreamHandlers";
import { IChatContent } from "@/core/models/Base";
import useTaskAbortedHandlers from "@/controllers/socket/global/useTaskAbortedHandlers";
import useGetProjectChatSessions from "@/controllers/api/board/chat/useGetProjectChatSessions";
import useBoardChatSessionCreatedHandlers from "@/controllers/socket/board/chat/useBoardChatSessionCreatedHandlers";
import { TChatScope } from "@langboard/core/types";
import { Utils } from "@langboard/core/utils";
import { EAgentPermissionLevel } from "@langboard/core/ai";
import { getBoardChatStore } from "@/core/stores/BoardChatStore";

export interface IBoardChatContext {
    projectUID: string;
    bot: InternalBotModel.TModel;
    socket: ISocketContext;
    isSending: bool;
    setIsSending: React.Dispatch<React.SetStateAction<bool>>;
    isUploading: bool;
    setIsUploading: React.Dispatch<React.SetStateAction<bool>>;
    isSessionListOpened: bool;
    setIsSessionListOpened: React.Dispatch<React.SetStateAction<bool>>;
    agentPermissionLevel: EAgentPermissionLevel;
    setAgentPermissionLevel: React.Dispatch<React.SetStateAction<EAgentPermissionLevel>>;
    selectedScope?: [TChatScope, string] | undefined;
    setSelectedScope: React.Dispatch<React.SetStateAction<[TChatScope, string] | undefined>>;
    lockedScope?: [TChatScope, string] | undefined;
    setLockedScope: React.Dispatch<React.SetStateAction<[TChatScope, string] | undefined>>;
    chatSessions: ChatSessionModel.TModel[];
    currentSessionUID?: string;
    setCurrentSessionUID: React.Dispatch<React.SetStateAction<string | undefined>>;
    chatTaskIdRef: React.RefObject<string | null>;
    scrollToBottomRef: React.RefObject<() => void>;
    isAtBottomRef: React.RefObject<bool>;
}

interface IBoardChatProviderProps {
    projectUID: string;
    bot?: InternalBotModel.TModel;
    children: React.ReactNode;
}

const initialContext = {
    projectUID: "",
    bot: {} as InternalBotModel.TModel,
    socket: {} as ISocketContext,
    isSending: false,
    setIsSending: () => {},
    isUploading: false,
    setIsUploading: () => {},
    isSessionListOpened: false,
    setIsSessionListOpened: () => {},
    agentPermissionLevel: EAgentPermissionLevel.Read,
    setAgentPermissionLevel: () => {},
    selectedScope: undefined,
    setSelectedScope: () => {},
    lockedScope: undefined,
    setLockedScope: () => {},
    chatSessions: [],
    currentSessionUID: undefined,
    setCurrentSessionUID: () => {},
    chatTaskIdRef: { current: null },
    scrollToBottomRef: { current: () => {} },
    isAtBottomRef: { current: true },
};

const BoardChatContext = createContext<IBoardChatContext>(initialContext);

export const BoardChatProvider = ({ projectUID, bot, children }: IBoardChatProviderProps): React.ReactNode => {
    const enabled = !!bot;
    const socket = useSocket();
    const [t] = useTranslation();
    const [isSending, setIsSendingState] = useState(false);
    const [isUploading, setIsUploadingState] = useState(false);
    const [isSessionListOpened, setIsSessionListOpened] = useState(false);
    const [agentPermissionLevel, setAgentPermissionLevel] = useState(EAgentPermissionLevel.Read);
    const [selectedScope, setSelectedScope] = useState<[TChatScope, string] | undefined>(undefined);
    const [lockedScope, setLockedScope] = useState<[TChatScope, string] | undefined>(undefined);
    const chatTaskIdRef = useRef<string | null>(null);
    const scrollToBottomRef = useRef<() => void>(() => {});
    const isAtBottomRef = useRef(true);
    const isSendingRef = useRef(isSending);
    const isUploadingRef = useRef(isUploading);
    const setIsSending = useCallback((value: React.SetStateAction<bool>) => {
        const next = Utils.Type.isFunction(value) ? value(isSendingRef.current) : value;
        isSendingRef.current = next;
        setIsSendingState(next);
    }, []);
    const setIsUploading = useCallback((value: React.SetStateAction<bool>) => {
        const next = Utils.Type.isFunction(value) ? value(isUploadingRef.current) : value;
        isUploadingRef.current = next;
        setIsUploadingState(next);
    }, []);
    const flatChatSessions = ChatSessionModel.Model.useModels(
        (model) => model.filterable_table === "project" && model.filterable_uid === projectUID,
        [projectUID]
    );
    const chatSessions = useMemo(
        () => [...flatChatSessions].sort((a, b) => (b.last_messaged_at?.getTime() ?? 0) - (a.last_messaged_at?.getTime() ?? 0)),
        [flatChatSessions]
    );
    const { mutateAsync } = useGetProjectChatSessions(projectUID);
    const isInitialMountedRef = useRef(false);
    const [currentSessionUID, setCurrentSessionUIDState] = useState<string | undefined>(() => getBoardChatStore().getCurrentSessionUID(projectUID));
    const currentSessionUIDRef = useRef(currentSessionUID);
    const setCurrentSessionUID = useCallback(
        (value: React.SetStateAction<string | undefined>) => {
            const next = Utils.Type.isFunction(value) ? value(currentSessionUIDRef.current) : value;
            currentSessionUIDRef.current = next;
            setCurrentSessionUIDState(next);
            getBoardChatStore().setCurrentSessionUID(projectUID, next);
        },
        [projectUID]
    );
    const currentSession = ChatSessionModel.Model.useModel((model) => model.uid === currentSessionUID, [currentSessionUID]);
    const currentAgentPermissionLevel = currentSession?.api_permission_level ?? agentPermissionLevel;
    const scrollToBottomAfterRender = useCallback(() => {
        if (!isAtBottomRef.current) {
            return;
        }

        requestAnimationFrame(() => {
            requestAnimationFrame(() => scrollToBottomRef.current());
        });
    }, []);

    const startCallback = useCallback((data: { ai_message: ChatMessageModel.Interface }) => {
        const chatMessage = ChatMessageModel.Model.fromOne({ ...data.ai_message, isPending: true }, true);
        const chatSession = ChatSessionModel.Model.getModel((model) => model.uid === chatMessage.chat_session_uid);
        if (chatSession) {
            chatSession.last_messaged_at = chatMessage.updated_at;
        }
        scrollToBottomRef.current();
    }, []);
    const bufferCallback = useCallback(
        (data: { uid: string; message?: IChatContent; chunk?: string; interrupt?: IChatContent["graph_interrupt"] }) => {
            const chatMessage = ChatMessageModel.Model.getModel(data.uid);
            if (!chatMessage) {
                return;
            }

            if (data.message) {
                if (data.message.content && chatMessage.isPending) {
                    chatMessage.isPending = undefined;
                }

                chatMessage.message = data.message;
            } else if (data.interrupt) {
                chatMessage.message = {
                    ...(chatMessage.message ?? { content: "" }),
                    graph_interrupt: data.interrupt,
                    graph_resume_error: null,
                };
                scrollToBottomAfterRender();
            } else if (data.chunk) {
                if (!chatMessage.message || !chatMessage.message.content) {
                    chatMessage.message = { content: "" };
                }

                if (data.chunk && chatMessage.isPending) {
                    chatMessage.isPending = undefined;
                }

                const message = {
                    content: `${chatMessage.message.content}${data.chunk}`,
                };

                chatMessage.message = message;

                if (isAtBottomRef.current) {
                    scrollToBottomRef.current();
                }
            }
        },
        [scrollToBottomAfterRender]
    );
    const endCallback = useCallback((data: { uid: string; status: "success" | "failed" | "aborted" }) => {
        const chatMessage = ChatMessageModel.Model.getModel(data.uid);
        const chatSession = chatMessage ? ChatSessionModel.Model.getModel((model) => model.uid === chatMessage.chat_session_uid) : undefined;
        if (data.status === "failed") {
            Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
        }

        if (data.status !== "success") {
            if (data.status === "failed") {
                ChatMessageModel.Model.deleteModel(data.uid);
            }
        }

        if (chatMessage && chatMessage.isPending) {
            chatMessage.isPending = undefined;
            if (chatSession) {
                chatSession.last_messaged_at = chatMessage.updated_at;
            }
        }

        setIsSending(false);

        if (isAtBottomRef.current) {
            scrollToBottomRef.current();
        }

        chatTaskIdRef.current = null;
    }, []);
    const errorCallback = useCallback((_: Event, fromServer: bool = true) => {
        const shouldShowError = (isSendingRef.current || isUploadingRef.current) && fromServer;

        ChatMessageModel.Model.getModels((model) => model.isPending ?? false).forEach((message) => {
            if (message.isPending) {
                message.isPending = undefined;
            }
        });
        setIsSending(false);
        if (shouldShowError) {
            Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
        }

        chatTaskIdRef.current = null;
    }, []);
    const sessionCreatedHandlers = useMemo(
        () =>
            useBoardChatSessionCreatedHandlers({
                projectUID,
                callback: (data) => {
                    if (!currentSessionUID) {
                        setCurrentSessionUID(data.session.uid);
                    }
                },
            }),
        [projectUID, currentSessionUID]
    );
    const sentHandlers = useMemo(() => useBoardChatSentHandlers({ projectUID, callback: () => scrollToBottomRef.current() }), [projectUID]);
    const cancelledHandlers = useMemo(
        () =>
            useTaskAbortedHandlers({
                callback: (data) => {
                    if (data.task_id !== chatTaskIdRef.current) {
                        return;
                    }

                    errorCallback({} as Event, false);
                },
            }),
        [errorCallback]
    );
    const streamHandlers = useMemo(
        () =>
            useBoardChatStreamHandlers({
                projectUID,
                callbacks: { start: startCallback, buffer: bufferCallback, end: endCallback, error: errorCallback },
            }),
        [projectUID, startCallback, bufferCallback, endCallback, errorCallback]
    );
    const handlers = useMemo(
        () => (enabled ? [sessionCreatedHandlers, sentHandlers, cancelledHandlers, streamHandlers] : []),
        [enabled, sessionCreatedHandlers, sentHandlers, cancelledHandlers, streamHandlers]
    );
    useSwitchSocketHandlers({
        socket,
        handlers,
        dependencies: handlers,
    });

    useEffect(() => {
        if (!enabled) return;
        mutateAsync({});
    }, [projectUID, enabled]);

    useEffect(() => {
        const storedSessionUID = getBoardChatStore().getCurrentSessionUID(projectUID);
        currentSessionUIDRef.current = storedSessionUID;
        setCurrentSessionUIDState(storedSessionUID);
        isInitialMountedRef.current = false;
    }, [projectUID]);

    useEffect(() => {
        if (!enabled || isInitialMountedRef.current || !chatSessions.length) {
            return;
        }

        if (currentSessionUID && chatSessions.some((session) => session.uid === currentSessionUID)) {
            isInitialMountedRef.current = true;
            return;
        }

        if (!currentSessionUID || !chatSessions.some((session) => session.uid === currentSessionUID)) {
            setCurrentSessionUID(chatSessions[0].uid);
        }

        isInitialMountedRef.current = true;
    }, [enabled, chatSessions, currentSessionUID, setCurrentSessionUID]);

    return (
        <BoardChatContext.Provider
            value={{
                projectUID,
                bot: bot ?? initialContext.bot,
                socket,
                isSending,
                setIsSending,
                isUploading,
                setIsUploading,
                isSessionListOpened,
                setIsSessionListOpened,
                agentPermissionLevel: currentAgentPermissionLevel,
                setAgentPermissionLevel,
                selectedScope,
                setSelectedScope,
                lockedScope,
                setLockedScope,
                chatSessions,
                currentSessionUID,
                setCurrentSessionUID,
                chatTaskIdRef,
                scrollToBottomRef,
                isAtBottomRef,
            }}
        >
            {enabled && currentSession && (
                <BoardChatSessionPermissionSync session={currentSession} setAgentPermissionLevel={setAgentPermissionLevel} />
            )}
            {children}
        </BoardChatContext.Provider>
    );
};

function BoardChatSessionPermissionSync({
    session,
    setAgentPermissionLevel,
}: {
    session: ChatSessionModel.TModel;
    setAgentPermissionLevel: React.Dispatch<React.SetStateAction<EAgentPermissionLevel>>;
}) {
    const apiPermissionLevel = session.useField("api_permission_level") ?? EAgentPermissionLevel.Read;

    useEffect(() => {
        setAgentPermissionLevel(apiPermissionLevel);
    }, [apiPermissionLevel, setAgentPermissionLevel]);

    return null;
}

export const useBoardChat = () => {
    const context = useContext(BoardChatContext);
    if (!context) {
        throw new Error("useBoardChat must be used within a BoardChatProvider");
    }
    return context;
};
