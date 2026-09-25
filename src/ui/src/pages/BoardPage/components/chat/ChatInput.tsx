import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import Select from "@/components/base/Select";
import Textarea from "@/components/base/Textarea";
import Toast from "@/components/base/Toast";
import useUploadProjectChatAttachment from "@/controllers/api/board/chat/useUploadProjectChatAttachment";
import useBoardChatCancelHandlers from "@/controllers/socket/board/chat/useBoardChatCancelHandlers";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { cn, measureTextAreaHeight } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";
import ChatTemplateListDialog from "@/pages/BoardPage/components/chat/ChatTemplateListDialog";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { MAX_FILE_SIZE_MB } from "@/constants";
import useBoardChatSentHandlers from "@/controllers/socket/board/chat/useBoardChatSentHandlers";
import useUpdateProjectChatSession from "@/controllers/api/board/chat/useUpdateProjectChatSession";
import { ChatSessionModel } from "@/core/models";
import ChatInputPreviewList from "@/pages/BoardPage/components/chat/ChatInputPreviewList";
import { ChatInputProvider, useChatInput } from "@/pages/BoardPage/components/chat/ChatInputProvider";
import ChatInputFileUpload from "@/pages/BoardPage/components/chat/ChatInputFileUpload";
import ChatInputAddScopeDialog from "@/pages/BoardPage/components/chat/ChatInputAddScopeDialog";
import { EAgentPermissionLevel } from "@langboard/core/ai";
import {
    CHAT_INPUT_MIN_HEIGHT,
    CHAT_PERMISSION_LEVEL_ICONS,
    CHAT_PERMISSION_LEVEL_OPTIONS,
    COMPACT_CHAT_SEND_AREA_WIDTH,
    FULL_CHAT_SEND_AREA_WIDTH,
    INLINE_CHAT_ACTIONS_WIDTH,
} from "@/pages/BoardPage/components/chat/constants";

export type TChatActionsMode = "full" | "icons" | "more";

export interface IChatInputProps {
    height: number;
    setHeight: (height: number) => void;
}

function ChatInput({ height, setHeight }: IChatInputProps) {
    return (
        <ChatInputProvider height={height} setHeight={setHeight}>
            <ChatInputDisplay />
        </ChatInputProvider>
    );
}

function ChatInputDisplay() {
    const {
        projectUID,
        isSending,
        setIsSending,
        isUploading,
        setIsUploading,
        currentSessionUID,
        selectedScope,
        setSelectedScope,
        lockedScope,
        agentPermissionLevel,
        chatTaskIdRef,
    } = useBoardChat();
    const { chatAttachmentRef, chatInputRef, height, file, setFile, setHeight } = useChatInput();
    const [t] = useTranslation();
    const { mutateAsync: uploadProjectChatAttachmentMutateAsync } = useUploadProjectChatAttachment();
    const { send: cancelChat } = useBoardChatCancelHandlers({ projectUID });
    const { send: sendChat } = useBoardChatSentHandlers({ projectUID });
    const abortControllerRef = useRef<AbortController | null>(null);
    const actionsContainerRef = useRef<HTMLDivElement | null>(null);
    const [actionsMode, setActionsMode] = useState<TChatActionsMode>("full");
    const updateHeight = useCallback(() => {
        if (!Utils.Type.isElement(chatInputRef.current, "textarea")) {
            return;
        }

        const selectionStart = chatInputRef.current.selectionStart;
        const selectionEnd = chatInputRef.current.selectionEnd;
        let measuredHeight = measureTextAreaHeight(chatInputRef.current);
        measuredHeight = Math.max(measuredHeight, CHAT_INPUT_MIN_HEIGHT);
        const maxHeight = window.innerHeight * 0.2;
        if (measuredHeight > maxHeight) {
            measuredHeight = maxHeight;
        }
        setHeight(measuredHeight);
        chatInputRef.current.selectionStart = selectionStart;
        chatInputRef.current.selectionEnd = selectionEnd;
    }, [setHeight]);

    const send = useCallback(async () => {
        if (!chatInputRef.current) {
            return;
        }

        if (isUploading) {
            abortControllerRef.current?.abort();
            return;
        }

        if (!isUploading && isSending) {
            cancelChat({
                project_uid: projectUID,
                task_id: chatTaskIdRef.current,
            });
            return;
        }

        setIsSending(true);

        let filePath: string | undefined = undefined;
        const attachment = file ?? chatAttachmentRef.current?.files?.[0];
        if (attachment) {
            setIsUploading(true);
            abortControllerRef.current = new AbortController();

            let result;
            try {
                result = await uploadProjectChatAttachmentMutateAsync({
                    project_uid: projectUID,
                    attachment,
                    abortController: abortControllerRef.current,
                });
            } catch {
                Toast.Add.error(
                    t("errors.Failed to upload attachment. File size may be too large (Max size is {size}MB).", { size: MAX_FILE_SIZE_MB })
                );
                setIsUploading(false);
                setIsSending(false);
                return;
            }

            setIsUploading(false);
            filePath = result.file_path;
        }

        const chatMessage = chatInputRef.current.value.trim();

        if (!chatMessage.length && !filePath) {
            setIsSending(false);
            return;
        }

        chatInputRef.current.value = "";
        if (chatAttachmentRef.current) {
            chatAttachmentRef.current.value = "";
        }
        setSelectedScope(undefined);
        setFile(null);
        updateHeight();

        let tried = 0;
        let triedTimeout: NodeJS.Timeout | undefined;
        const trySendChat = () => {
            if (tried >= 5) {
                Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
                setIsSending(false);
                return true;
            }

            ++tried;

            chatTaskIdRef.current = Utils.String.Token.uuid();

            const [scopeTable, scopeUID] = lockedScope || selectedScope || [undefined, undefined];

            return sendChat({
                message: chatMessage,
                file_path: filePath,
                task_id: chatTaskIdRef.current,
                session_uid: currentSessionUID,
                scope_table: scopeTable,
                scope_uid: scopeUID,
                api_permission_level: agentPermissionLevel,
            }).isConnected;
        };

        const trySendChatWrapper = () => {
            if (triedTimeout) {
                clearTimeout(triedTimeout);
                triedTimeout = undefined;
            }

            const isSent = trySendChat();
            if (!isSent) {
                triedTimeout = setTimeout(trySendChatWrapper, 1000);
            }
        };

        if (!trySendChat()) {
            triedTimeout = setTimeout(trySendChatWrapper, 1000);
        }
    }, [
        updateHeight,
        isSending,
        setIsSending,
        isUploading,
        setIsUploading,
        currentSessionUID,
        selectedScope,
        lockedScope,
        agentPermissionLevel,
        file,
        setSelectedScope,
    ]);

    useEffect(() => {
        const node = actionsContainerRef.current;
        if (!node || typeof ResizeObserver === "undefined") {
            return;
        }

        const updateCompactState = () => {
            const width = node.clientWidth;

            if (width >= INLINE_CHAT_ACTIONS_WIDTH + FULL_CHAT_SEND_AREA_WIDTH) {
                setActionsMode("full");
                return;
            }

            if (width >= INLINE_CHAT_ACTIONS_WIDTH + COMPACT_CHAT_SEND_AREA_WIDTH) {
                setActionsMode("icons");
                return;
            }

            setActionsMode("more");
        };
        updateCompactState();

        const resizeObserver = new ResizeObserver(updateCompactState);
        resizeObserver.observe(node);

        return () => {
            resizeObserver.disconnect();
        };
    }, []);

    const handleTextAreaKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.shiftKey && e.key === "Enter") {
            return;
        }

        if (e.key === "Enter") {
            e.preventDefault();
            e.stopPropagation();
            send();
        }
    };

    return (
        <Flex direction="col" w="full" position="relative" className="shrink-0 border-t bg-background">
            <Flex
                direction="col"
                className={cn(
                    "relative w-full overflow-hidden border border-transparent bg-card",
                    "transition-colors focus-within:border-primary/60"
                )}
            >
                <ChatInputPreviewList />
                <Textarea
                    placeholder={t("project.Enter a message")}
                    className={cn(
                        "max-h-[20vh] min-h-20 resize-none overflow-y-auto rounded-none",
                        "border-0 bg-transparent px-3 pb-11 pt-2 shadow-none focus-visible:ring-0"
                    )}
                    resize="none"
                    disabled={isSending}
                    style={{ height }}
                    onKeyDown={handleTextAreaKeyDown}
                    onChange={updateHeight}
                    ref={chatInputRef}
                />
                <Flex
                    ref={actionsContainerRef}
                    position="absolute"
                    bottom="0"
                    minW="0"
                    px="2"
                    py="1"
                    justify="between"
                    items="center"
                    className="pointer-events-none inset-x-0 bg-card/95 backdrop-blur"
                >
                    <Flex items="center" gap="1" className="pointer-events-auto min-w-0">
                        {actionsMode === "more" ? (
                            <ChatInputMoreActions className="shrink-0" chatInputRef={chatInputRef} updateHeight={updateHeight} />
                        ) : (
                            <ChatInputActions chatInputRef={chatInputRef} updateHeight={updateHeight} />
                        )}
                    </Flex>
                    <Flex items="center" gap="2" className="pointer-events-auto shrink-0">
                        <ChatInputPermissionLevel showLabel={actionsMode === "full"} />
                        <Button
                            type="button"
                            variant={isSending ? "secondary" : "default"}
                            size={isSending || actionsMode === "more" ? "icon-sm" : "sm"}
                            className={cn("gap-1.5 rounded-full", actionsMode === "more" ? "px-0" : "px-3")}
                            title={t(isSending ? "project.Stop" : "project.Send a message")}
                            titleSide="top"
                            onClick={send}
                        >
                            <IconComponent
                                icon={isSending ? (isUploading ? "loader-circle" : "square") : "send"}
                                size="3"
                                className={cn(isUploading && "animate-spin")}
                            />
                            {!isSending && actionsMode !== "more" && t("common.Send")}
                        </Button>
                    </Flex>
                </Flex>
            </Flex>
        </Flex>
    );
}

interface IChatInputActionsProps {
    chatInputRef: React.RefObject<HTMLTextAreaElement | null>;
    updateHeight: () => void;
}

interface IChatInputMoreActionsProps extends IChatInputActionsProps {
    className?: string;
}

function ChatInputActions({ chatInputRef, updateHeight }: IChatInputActionsProps) {
    return (
        <>
            <ChatInputFileUpload />
            <ChatTemplateListDialog chatInputRef={chatInputRef} updateHeight={updateHeight} />
            <ChatInputAddScopeDialog />
        </>
    );
}

function ChatInputPermissionLevel({ showLabel }: { showLabel: bool }) {
    const { agentPermissionLevel, currentSessionUID, isSending, projectUID, setAgentPermissionLevel } = useBoardChat();
    const [t] = useTranslation();
    const { mutate } = useUpdateProjectChatSession({ interceptToast: false });
    const isFullAccess = agentPermissionLevel === EAgentPermissionLevel.FullAccess;
    const permissionLevelLabel = t(`project.permissions.${agentPermissionLevel}`);

    const handlePermissionLevelChange = (value: string) => {
        const apiPermissionLevel = value as EAgentPermissionLevel;
        const previousPermissionLevel = agentPermissionLevel;
        const currentSession = currentSessionUID ? ChatSessionModel.Model.getModel(currentSessionUID) : undefined;

        setAgentPermissionLevel(apiPermissionLevel);
        if (currentSession) {
            currentSession.api_permission_level = apiPermissionLevel;
        }

        if (!currentSessionUID) {
            return;
        }

        mutate(
            {
                uid: projectUID,
                session_uid: currentSessionUID,
                api_permission_level: apiPermissionLevel,
            },
            {
                onError: () => {
                    setAgentPermissionLevel(previousPermissionLevel);
                    if (currentSession) {
                        currentSession.api_permission_level = previousPermissionLevel;
                    }
                },
            }
        );
    };

    return (
        <Select.Root value={agentPermissionLevel} onValueChange={handlePermissionLevelChange}>
            <Select.Trigger
                disabled={isSending}
                className={cn(
                    "h-8 min-w-0 gap-2 px-2 py-1 text-xs [&>span]:min-w-0",
                    showLabel ? "w-36" : "w-16",
                    isFullAccess && "border-warning-border bg-warning text-warning-foreground focus:ring-warning-border"
                )}
                title={t("project.Permission")}
            >
                <Flex items="center" gap="1.5" className="min-w-0 flex-1">
                    <IconComponent icon={CHAT_PERMISSION_LEVEL_ICONS[agentPermissionLevel]} size="3" className="shrink-0" />
                    {showLabel && <span className="min-w-0 truncate">{permissionLevelLabel}</span>}
                </Flex>
            </Select.Trigger>
            <Select.Content align="end" side="top">
                {CHAT_PERMISSION_LEVEL_OPTIONS.map((permissionLevel) => (
                    <Select.Item
                        key={`chat-permission-level-${permissionLevel}`}
                        value={permissionLevel}
                        className={cn(permissionLevel === EAgentPermissionLevel.FullAccess && "text-warning-foreground focus:bg-warning")}
                    >
                        <Flex items="center" gap="1.5">
                            <IconComponent icon={CHAT_PERMISSION_LEVEL_ICONS[permissionLevel]} size="3" />
                            {t(`project.permissions.${permissionLevel}`)}
                        </Flex>
                    </Select.Item>
                ))}
            </Select.Content>
        </Select.Root>
    );
}

function ChatInputMoreActions({ className, chatInputRef, updateHeight }: IChatInputMoreActionsProps) {
    const [t] = useTranslation();

    return (
        <Popover.Root>
            <Popover.Trigger asChild>
                <Button type="button" variant="ghost" size="icon-sm" className={className} title={t("common.More")} titleSide="top">
                    <IconComponent icon="plus" size="4" />
                </Button>
            </Popover.Trigger>
            <Popover.Content align="start" side="top" className="w-56 p-2">
                <Flex direction="col" gap="1">
                    <ChatInputFileUpload showLabel className="w-full" />
                    <ChatTemplateListDialog showLabel className="w-full" chatInputRef={chatInputRef} updateHeight={updateHeight} />
                    <ChatInputAddScopeDialog showLabel className="w-full" />
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

export default ChatInput;
