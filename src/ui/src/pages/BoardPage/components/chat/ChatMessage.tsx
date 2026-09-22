import IconComponent from "@/components/base/IconComponent";
import Badge from "@/components/base/Badge";
import { ChatBubble, ChatBubbleAvatar, ChatBubbleMessage } from "@/components/Chat/ChatBubble";
import { ChatMessageModel, GraphApprovalRequestModel } from "@/core/models";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import Button from "@/components/base/Button";
import Toast from "@/components/base/Toast";
import Input from "@/components/base/Input";
import { IGraphInterruptContent } from "@/core/models/Base";
import { EGraphApprovalStatus } from "@/core/models/GraphApprovalRequestModel";
import { EInternalBotRunStatus } from "@/core/constants/InternalBotRun";
import { cn } from "@/core/utils/ComponentUtils";
import { SocketEvents } from "@langboard/core/constants";
import { ESocketTopic } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IChatMessageProps {
    chatMessage: ChatMessageModel.TModel;
}

function ChatMessage({ chatMessage }: IChatMessageProps): React.JSX.Element {
    const message = chatMessage.useField("message");
    const isReceived = chatMessage.useField("is_received");
    const isPending = chatMessage.useField("isPending");
    const variant = isReceived ? "received" : "sent";
    const graphInterrupt = message?.graph_interrupt;

    return (
        <ChatBubble key={`chat-bubble-${chatMessage.uid}`} variant={variant} message={message}>
            {isReceived && <ChatMessageBotAvatar />}
            <div className="flex min-w-0 max-w-full flex-col gap-2">
                {isPending ? <ChatBubbleMessage isLoading /> : !graphInterrupt && <ChatBubbleMessage variant={variant} message={message} />}
                {isReceived && !isPending && graphInterrupt && (
                    <ChatGraphInterruptActions chatMessageUID={chatMessage.uid} interrupt={graphInterrupt} resumeError={message.graph_resume_error} />
                )}
            </div>
        </ChatBubble>
    );
}

function ChatMessageBotAvatar() {
    const { bot } = useBoardChat();
    const displayName = bot.useField("display_name");
    const avatar = bot.useField("avatar");

    return (
        <ChatBubbleAvatar
            fallback={<IconComponent icon="bot" className="size-[60%]" />}
            src={avatar}
            title={displayName}
            titleSide="top"
            titleAlign="start"
        />
    );
}

interface IChatGraphInterruptActionsProps {
    chatMessageUID: string;
    interrupt: IGraphInterruptContent;
    resumeError?: string | null;
}

type TGraphResumeAction = "approve" | "reject" | "instruction";

function ChatGraphInterruptActions({ chatMessageUID, interrupt, resumeError }: IChatGraphInterruptActionsProps) {
    const interruptValue = useMemo(() => getGraphInterruptValue(interrupt), [interrupt]);
    const threadID = Utils.Type.isString(interruptValue.thread_id) ? interruptValue.thread_id : undefined;
    const sessionID = Utils.Type.isString(interruptValue.session_id) ? interruptValue.session_id : undefined;
    const approvalUID = Utils.Type.isString(interruptValue.approval_uid) ? interruptValue.approval_uid : undefined;
    const message = Utils.Type.isString(interruptValue.message) ? interruptValue.message : undefined;
    const approval = GraphApprovalRequestModel.Model.useModel(approvalUID ?? "");
    const submittedInstruction = Utils.Type.isString(interruptValue.instruction) ? interruptValue.instruction : undefined;

    if (approval) {
        return (
            <ChatGraphInterruptApprovalActions
                chatMessageUID={chatMessageUID}
                threadID={threadID}
                sessionID={sessionID}
                approvalUID={approvalUID}
                approval={approval}
                message={message}
                submittedInstruction={submittedInstruction}
                resumeError={resumeError}
                interrupt={interrupt}
            />
        );
    }

    return (
        <ChatGraphInterruptActionsContent
            chatMessageUID={chatMessageUID}
            threadID={threadID}
            sessionID={sessionID}
            approvalUID={approvalUID}
            message={message}
            status={getGraphApprovalStatus(interruptValue.status)}
            resolvedByUserUID={Utils.Type.isString(interruptValue.resolved_by_user_uid) ? interruptValue.resolved_by_user_uid : undefined}
            rejectionReason={Utils.Type.isString(interruptValue.rejection_reason) ? interruptValue.rejection_reason : undefined}
            submittedInstruction={submittedInstruction}
            resumeError={resumeError}
            interrupt={interrupt}
        />
    );
}

interface IChatGraphInterruptApprovalActionsProps extends Omit<
    IChatGraphInterruptActionsContentProps,
    "status" | "resolvedByUserUID" | "rejectionReason"
> {
    approval: GraphApprovalRequestModel.TModel;
}

function ChatGraphInterruptApprovalActions({ approval, approvalUID, ...props }: IChatGraphInterruptApprovalActionsProps) {
    const status = approval.useField("status");
    const resolvedByUserUID = approval.useField("resolved_by_user_uid");
    const rejectionReason = approval.useField("rejection_reason");
    const durableRunStatus = approval.useField("durable_run_status");

    useEffect(() => {
        if (!approvalUID || !status || status === EGraphApprovalStatus.Pending) {
            return;
        }

        GraphApprovalRequestModel.Model.deleteModel(approvalUID);
    }, [approvalUID, status]);

    return (
        <ChatGraphInterruptActionsContent
            {...props}
            approvalUID={approvalUID}
            status={status}
            resolvedByUserUID={resolvedByUserUID}
            rejectionReason={rejectionReason}
            durableRunStatus={durableRunStatus}
        />
    );
}

interface IChatGraphInterruptActionsContentProps {
    chatMessageUID: string;
    threadID?: string;
    sessionID?: string;
    approvalUID?: string;
    message?: string;
    status?: EGraphApprovalStatus;
    resolvedByUserUID?: string;
    rejectionReason?: string;
    durableRunStatus?: EInternalBotRunStatus | null;
    submittedInstruction?: string;
    resumeError?: string | null;
    interrupt: IGraphInterruptContent;
}

function ChatGraphInterruptActionsContent({
    chatMessageUID,
    threadID,
    sessionID,
    approvalUID,
    message,
    status,
    resolvedByUserUID,
    rejectionReason,
    durableRunStatus,
    submittedInstruction,
    resumeError,
    interrupt,
}: IChatGraphInterruptActionsContentProps) {
    const { projectUID, socket } = useBoardChat();
    const [t] = useTranslation();
    const [resumingAction, setResumingAction] = useState<TGraphResumeAction>();
    const [instruction, setInstruction] = useState("");
    const isResuming = !!resumingAction;
    const durableRunBlocked =
        durableRunStatus !== undefined && durableRunStatus !== null && durableRunStatus !== EInternalBotRunStatus.AwaitingApproval;

    useEffect(() => {
        setResumingAction(undefined);
    }, [interrupt]);

    useEffect(() => {
        if (resumeError) {
            setResumingAction(undefined);
        }
    }, [resumeError]);

    if (!threadID) {
        return null;
    }

    if (status && status !== EGraphApprovalStatus.Pending) {
        return (
            <div className={cn("w-full min-w-[12rem] max-w-full rounded-xl border p-3 text-xs shadow-sm", getApprovalResolvedClassName(status))}>
                <div className="flex flex-wrap items-center gap-2">
                    <div className="font-semibold">{t("bot.Human input required")}</div>
                    <Badge variant="outline" className="px-1.5 py-0 text-[10px]">
                        {t(`bot.approvalStatuses.${status}`)}
                    </Badge>
                </div>
                {message && <div className="mt-1 opacity-80">{message}</div>}
                {submittedInstruction && (
                    <div className="border-current/20 mt-2 rounded-md border bg-background/30 p-2 opacity-90">
                        <div className="mb-1 font-medium">{t("bot.Submitted instruction")}</div>
                        <div className="whitespace-pre-wrap">{submittedInstruction}</div>
                    </div>
                )}
                {resolvedByUserUID && <div className="mt-2 opacity-70">{t("bot.Resolved by", { user: resolvedByUserUID })}</div>}
                {status === EGraphApprovalStatus.Rejected && rejectionReason && <div className="mt-2 opacity-80">{rejectionReason}</div>}
            </div>
        );
    }

    if (durableRunBlocked) {
        return (
            <div
                className={cn(
                    "w-full min-w-[12rem] max-w-full rounded-xl border p-3 text-xs shadow-sm",
                    "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-50"
                )}
            >
                <div className="font-semibold">{t("bot.Human input required")}</div>
                {message && <div className="mt-1 opacity-80">{message}</div>}
                <div className="mt-2 opacity-80">{t(`bot.runStatuses.${durableRunStatus}`)}</div>
                {durableRunStatus === EInternalBotRunStatus.Uncertain && <div className="mt-2 opacity-80">{t("bot.Run outcome unknown")}</div>}
            </div>
        );
    }

    const resume = (action: TGraphResumeAction, payload: Record<string, unknown>) => {
        const chatMessage = ChatMessageModel.Model.getModel(chatMessageUID);
        if (chatMessage?.message?.graph_resume_error) {
            chatMessage.message = { ...chatMessage.message, graph_resume_error: null };
        }
        setResumingAction(action);
        const result = socket.send({
            topic: ESocketTopic.Board,
            topicId: projectUID,
            eventName: SocketEvents.CLIENT.BOARD.CHAT.RESUME,
            data: {
                message_uid: chatMessageUID,
                thread_id: threadID,
                session_id: sessionID,
                approval_uid: approvalUID,
                resume: payload,
            },
        });

        if (!result.isConnected) {
            setResumingAction(undefined);
            Toast.Add.error(t("errors.Server has been temporarily disabled. Please try again later."));
        }
    };
    const resumeWithInstruction = () => {
        const trimmedInstruction = instruction.trim();
        if (!trimmedInstruction) {
            return;
        }

        resume("instruction", {
            approved: false,
            rejected: false,
            instruction: trimmedInstruction,
        });
    };
    const handleInstructionKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
        if (event.key !== "Enter") {
            return;
        }

        event.preventDefault();
        resumeWithInstruction();
    };

    return (
        <div
            className={cn(
                "w-full min-w-[12rem] max-w-full rounded-xl border",
                "border-amber-300 bg-amber-50 p-3 text-xs text-amber-950 shadow-sm dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-50"
            )}
        >
            <div className="font-semibold">{t("bot.Human input required")}</div>
            {message && <div className="mt-1 text-amber-900/80 dark:text-amber-100/80">{message}</div>}
            {resumeError && <div className="mt-2 text-destructive dark:text-red-300">{resumeError}</div>}
            <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button size="sm" onClick={() => resume("approve", { approved: true, rejected: false })} disabled={isResuming}>
                    {t(resumingAction === "approve" ? "bot.Resuming..." : "bot.Approve")}
                </Button>
                <Button size="sm" variant="outline" onClick={() => resume("reject", { approved: false, rejected: true })} disabled={isResuming}>
                    {t(resumingAction === "reject" ? "bot.Resuming..." : "bot.Reject")}
                </Button>
                <Input
                    h="sm"
                    wrapperProps={{ className: "min-w-32 flex-1" }}
                    className={cn(
                        "min-w-0 border-amber-300/70 bg-white/70 text-xs text-foreground",
                        "placeholder:text-muted-foreground dark:border-amber-400/30 dark:bg-background/60"
                    )}
                    placeholder={t("bot.Tell graph what to do instead")}
                    value={instruction}
                    disabled={isResuming}
                    onChange={(event) => setInstruction(event.target.value)}
                    onKeyDown={handleInstructionKeyDown}
                />
                <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={isResuming || !instruction.trim()}
                    title={t(resumingAction === "instruction" ? "bot.Resuming..." : "common.Send")}
                    onClick={resumeWithInstruction}
                >
                    <IconComponent icon={resumingAction === "instruction" ? "loader-circle" : "send"} size="3.5" />
                </Button>
            </div>
        </div>
    );
}

function getGraphInterruptValue(interrupt: IGraphInterruptContent): Record<string, unknown> {
    if (Utils.Type.isObject<Record<string, unknown>>(interrupt.value)) {
        return interrupt.value as Record<string, unknown>;
    }

    if ("type" in interrupt && interrupt.type === "approval_request") {
        return interrupt as Record<string, unknown>;
    }

    return {};
}

function getGraphApprovalStatus(value: unknown): EGraphApprovalStatus | undefined {
    if (!Utils.Type.isString(value)) {
        return undefined;
    }

    return Object.values(EGraphApprovalStatus).includes(value as EGraphApprovalStatus) ? (value as EGraphApprovalStatus) : undefined;
}

function getApprovalResolvedClassName(status: EGraphApprovalStatus): string {
    switch (status) {
        case EGraphApprovalStatus.Approved:
        case EGraphApprovalStatus.Resolved:
            return "border-green-300 bg-green-50 text-green-950 dark:border-green-400/30 dark:bg-green-500/10 dark:text-green-50";
        case EGraphApprovalStatus.Rejected:
            return "border-red-300 bg-red-50 text-red-950 dark:border-red-400/40 dark:bg-red-500/10 dark:text-red-50";
        case EGraphApprovalStatus.Expired:
        case EGraphApprovalStatus.Cancelled:
            return "border-muted-foreground/30 bg-muted/30 text-muted-foreground";
        case EGraphApprovalStatus.Pending:
            return "border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-50";
    }
}

export default ChatMessage;
