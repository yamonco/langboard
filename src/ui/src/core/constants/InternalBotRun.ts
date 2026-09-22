export enum EInternalBotRunKind {
    EditorChat = "editor_chat",
    EditorCopilot = "editor_copilot",
}

export enum EInternalBotRunStatus {
    Accepted = "accepted",
    Streaming = "streaming",
    AwaitingApproval = "awaiting_approval",
    Resuming = "resuming",
    Completed = "completed",
    Failed = "failed",
    Cancelled = "cancelled",
    Uncertain = "uncertain",
}

export const EDITOR_AI_STATUS_POLL_INTERVAL_MS = 1_000;
export const EDITOR_AI_STATUS_MAX_POLLS = 120;
