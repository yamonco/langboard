import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { ChatMessageModel, ChatSessionModel, GraphApprovalRequestModel, InternalBotModel } from "@/core/models";
import { ISocketContext, useSocket } from "@/core/providers/SocketProvider";
import useBoardChatSentHandlers from "@/controllers/socket/board/chat/useBoardChatSentHandlers";
import useBoardChatSendFailedHandlers from "@/controllers/socket/board/chat/useBoardChatSendFailedHandlers";
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
import { ESocketStatus } from "@langboard/core/enums";
import { EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { getBoardChatStore } from "@/core/stores/BoardChatStore";
import useGetProjectChatRun from "@/controllers/api/board/chat/useGetProjectChatRun";
import { BOARD_CHAT_ACCEPTANCE_GRACE_MS } from "@/core/constants/BoardChatRun";
import { EInternalBotRunStatus } from "@/core/constants/InternalBotRun";
import { ESocketTopic } from "@langboard/core/enums";
import { useAuth } from "@/core/providers/AuthProvider";

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
    setChatTaskId: (taskId: string | null) => void;
    scrollToBottomRef: React.RefObject<() => void>;
    isAtBottomRef: React.RefObject<bool>;
}

interface IBoardChatProviderProps {
    projectUID: string;
    bot: InternalBotModel.TModel;
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
    setChatTaskId: () => {},
    scrollToBottomRef: { current: () => {} },
    isAtBottomRef: { current: true },
};

const BoardChatContext = createContext<IBoardChatContext>(initialContext);

export const BoardChatProvider = ({ projectUID, bot, children }: IBoardChatProviderProps): React.ReactNode => {
    const { currentUser } = useAuth();
    const socket = useSocket();
    const [t] = useTranslation();
    const [isSending, setIsSendingState] = useState(false);
    const [isUploading, setIsUploadingState] = useState(false);
    const [isSessionListOpened, setIsSessionListOpened] = useState(false);
    const [agentPermissionLevel, setAgentPermissionLevel] = useState(EAgentPermissionLevel.Read);
    const [selectedScope, setSelectedScope] = useState<[TChatScope, string] | undefined>(undefined);
    const [lockedScope, setLockedScope] = useState<[TChatScope, string] | undefined>(undefined);
    const chatTaskIdRef = useRef<string | null>(null);
    const setChatTaskId = useCallback(
        (taskId: string | null) => {
            chatTaskIdRef.current = taskId;
            if (currentUser) {
                getBoardChatStore().setPendingTaskId(currentUser.uid, projectUID, taskId);
            }
        },
        [currentUser, projectUID]
    );
    const [recoveringTaskId, setRecoveringTaskId] = useState<string | null>(null);
    const isReconcilingRef = useRef(false);
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
    const { mutateAsync: getProjectChatRun } = useGetProjectChatRun(projectUID);
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
        (data: {
            uid: string;
            message?: IChatContent;
            chunk?: string;
            interrupt?: IChatContent["graph_interrupt"];
            resume_error_code?: ESocketStatus;
        }) => {
            const chatMessage = ChatMessageModel.Model.getModel(data.uid);
            if (!chatMessage) {
                return;
            }

            if (data.resume_error_code) {
                const errorKey =
                    data.resume_error_code === ESocketStatus.WS_3000_UNAUTHORIZED
                        ? "errors.requests.AU1004"
                        : data.resume_error_code === ESocketStatus.WS_3003_FORBIDDEN
                          ? "errors.requests.PE1001"
                          : data.resume_error_code === ESocketStatus.WS_4001_INVALID_DATA
                            ? "errors.requests.NF2021"
                            : "errors.Server has been temporarily disabled. Please try again later.";
                chatMessage.message = {
                    ...(chatMessage.message ?? { content: "" }),
                    graph_resume_error: t(errorKey),
                };
            } else if (data.message) {
                if (data.message.content && chatMessage.isPending) {
                    chatMessage.isPending = undefined;
                }

                chatMessage.message = data.message;
                removeResolvedGraphApproval(data.message);
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
    const endCallback = useCallback(
        (data: { uid: string; status: "success" | "failed" | "aborted" }) => {
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

            setChatTaskId(null);
            setRecoveringTaskId(null);
        },
        [setChatTaskId]
    );
    const errorCallback = useCallback(
        (_: Event, fromServer: bool = true) => {
            const recovering = fromServer && chatTaskIdRef.current !== null;
            const shouldShowError = (isSendingRef.current || isUploadingRef.current) && fromServer && !recovering;

            ChatMessageModel.Model.getModels((model) => model.isPending ?? false).forEach((message) => {
                if (message.isPending) {
                    message.isPending = undefined;
                }
            });
            setIsSending(recovering);
            if (shouldShowError) {
                Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
            }

            if (fromServer && chatTaskIdRef.current) {
                setRecoveringTaskId(chatTaskIdRef.current);
            } else {
                setChatTaskId(null);
                setRecoveringTaskId(null);
            }
        },
        [setChatTaskId]
    );
    const reconcileTask = useCallback(
        async (taskId: string) => {
            if (isReconcilingRef.current || chatTaskIdRef.current !== taskId) {
                return;
            }

            isReconcilingRef.current = true;
            try {
                const run = await getProjectChatRun(taskId);
                if (chatTaskIdRef.current !== taskId) {
                    return;
                }

                if (!ChatMessageModel.Model.getModel(run.user_message.uid)) {
                    ChatMessageModel.Model.fromOne(run.user_message, true);
                }
                const active = [EInternalBotRunStatus.Accepted, EInternalBotRunStatus.Streaming, EInternalBotRunStatus.Resuming].includes(run.status);
                if (run.ai_message) {
                    if (!active || !ChatMessageModel.Model.getModel(run.ai_message.uid)) {
                        ChatMessageModel.Model.fromOne({ ...run.ai_message, isPending: active }, true);
                    }
                } else if (run.ai_message_uid && !active) {
                    ChatMessageModel.Model.deleteModel(run.ai_message_uid);
                }

                if (!currentSessionUIDRef.current) {
                    setCurrentSessionUID(run.session_uid);
                }
                if (!ChatSessionModel.Model.getModel((session) => session.uid === run.session_uid)) {
                    void mutateAsync({});
                }
                if (active) {
                    setIsSending(true);
                    return;
                }

                setIsSending(false);
                setChatTaskId(null);
                setRecoveringTaskId(null);
                if (run.status === EInternalBotRunStatus.Failed || run.status === EInternalBotRunStatus.Uncertain) {
                    Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
                }
            } catch (error) {
                const status = axios.isAxiosError(error) ? error.response?.status : undefined;
                const pendingTask = currentUser ? getBoardChatStore().getPendingTask(currentUser.uid, projectUID) : null;
                const pendingTaskAge = pendingTask ? Date.now() - pendingTask.createdAt : null;
                if (
                    status === 404 &&
                    pendingTask?.taskId === taskId &&
                    pendingTaskAge !== null &&
                    pendingTaskAge >= 0 &&
                    pendingTaskAge < BOARD_CHAT_ACCEPTANCE_GRACE_MS
                ) {
                    return;
                }
                if (chatTaskIdRef.current === taskId && (status === 401 || status === 403 || status === 404)) {
                    setChatTaskId(null);
                    setRecoveringTaskId(null);
                    setIsSending(false);
                    if (status === 404) {
                        void mutateAsync({});
                    }
                    if (status !== 401) {
                        Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
                    }
                }
            } finally {
                isReconcilingRef.current = false;
            }
        },
        [currentUser, getProjectChatRun, mutateAsync, projectUID, setChatTaskId, setCurrentSessionUID, setIsSending]
    );
    useEffect(() => {
        if (!recoveringTaskId) {
            return;
        }

        const key = `board-chat-recovery-${projectUID}`;
        socket.subscribeTopicNotifier({
            topic: ESocketTopic.Board,
            topicId: projectUID,
            key,
            notifier: (_, isSubscribed) => {
                if (isSubscribed) {
                    void reconcileTask(recoveringTaskId);
                }
            },
        });
        const interval = window.setInterval(() => void reconcileTask(recoveringTaskId), 3000);
        return () => {
            socket.unsubscribeTopicNotifier({ topic: ESocketTopic.Board, topicId: projectUID, key });
            window.clearInterval(interval);
        };
    }, [projectUID, recoveringTaskId, reconcileTask, socket]);
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
    const sendFailedHandlers = useMemo(
        () =>
            useBoardChatSendFailedHandlers({
                projectUID,
                callback: (data) => {
                    if (chatTaskIdRef.current !== data.task_id) {
                        return;
                    }

                    if (data.already_started) {
                        setRecoveringTaskId(data.task_id);
                        return;
                    }
                    errorCallback({} as Event, false);
                    Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
                },
            }),
        [projectUID, errorCallback]
    );
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
        () => [sessionCreatedHandlers, sentHandlers, sendFailedHandlers, cancelledHandlers, streamHandlers],
        [sessionCreatedHandlers, sentHandlers, sendFailedHandlers, cancelledHandlers, streamHandlers]
    );
    useSwitchSocketHandlers({
        socket,
        handlers,
        dependencies: handlers,
    });

    useEffect(() => {
        mutateAsync({});
    }, [projectUID]);

    useEffect(() => {
        const storedSessionUID = getBoardChatStore().getCurrentSessionUID(projectUID);
        const pendingTaskId = currentUser ? (getBoardChatStore().getPendingTask(currentUser.uid, projectUID)?.taskId ?? null) : null;
        chatTaskIdRef.current = pendingTaskId;
        setRecoveringTaskId(pendingTaskId);
        setIsSending(Boolean(pendingTaskId));
        currentSessionUIDRef.current = storedSessionUID;
        setCurrentSessionUIDState(storedSessionUID);
        isInitialMountedRef.current = false;
    }, [projectUID, currentUser]);

    useEffect(() => {
        if (isInitialMountedRef.current || !chatSessions.length) {
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
    }, [chatSessions, currentSessionUID, setCurrentSessionUID]);

    return (
        <BoardChatContext.Provider
            value={{
                projectUID,
                bot,
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
                setChatTaskId,
                scrollToBottomRef,
                isAtBottomRef,
            }}
        >
            {currentSession && <BoardChatSessionPermissionSync session={currentSession} setAgentPermissionLevel={setAgentPermissionLevel} />}
            {children}
        </BoardChatContext.Provider>
    );
};

function removeResolvedGraphApproval(message: IChatContent): void {
    const value = message.graph_interrupt?.value;
    if (!Utils.Type.isObject<Record<string, unknown>>(value)) {
        return;
    }

    const approvalUID = Utils.Type.isString(value.approval_uid) ? value.approval_uid : undefined;
    const status = Utils.Type.isString(value.status) ? value.status : undefined;
    if (!approvalUID || !status || status === EGraphApprovalStatus.Pending) {
        return;
    }

    GraphApprovalRequestModel.Model.deleteModel(approvalUID);
}

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
