export const TASK_METADATA_KEYS = {
    source: "task.source",
    sourceUrl: "task.source_url",
    externalId: "task.external_id",
    type: "task.type",
    assignedAgent: "task.assigned_agent",
    assignedBotUID: "task.assigned_bot_uid",
    acceptanceCriteria: "task.acceptance_criteria",
    riskLevel: "task.risk_level",
    relatedFiles: "task.related_files",
    prUrl: "task.pr_url",
} as const;

export const SYSTEM_TASK_METADATA_KEYS = {
    verification: "__system.task.verification",
    failure: "__system.task.failure",
    run: "__system.task.run",
    suggestions: "__system.task.suggestions",
    bypass: "__system.task.bypass",
} as const;

export enum ETaskRiskLevel {
    Low = "low",
    Medium = "medium",
    High = "high",
}

export enum ETaskVerificationStatus {
    Pending = "pending",
    Running = "running",
    Passed = "passed",
    Failed = "failed",
    Skipped = "skipped",
}

export interface ITaskVerificationMetadata {
    status?: string;
    summary?: string;
    checked_at?: string;
}

export interface ITaskFailureMetadata {
    status?: string;
    summary?: string;
    cause?: string;
    reproduction?: string[];
    recommendation?: string[];
    checked_at?: string;
}

export interface ITaskRunMetadata {
    status?: string;
    run_id?: string;
    bot_log_uid?: string;
    assigned_agent?: string;
    summary?: string;
    started_at?: string;
    finished_at?: string;
    recorded_at?: string;
}

export interface ITaskSuggestionMetadata {
    title?: string;
    type?: string;
    risk_level?: string;
    assigned_agent?: string;
    assigned_bot_uid?: string;
    acceptance_criteria?: string[];
    related_files?: string[];
    created_card_uid?: string;
}

export interface ITaskBypassMetadata {
    allowed?: bool;
    requires_approval?: bool;
    reason?: string;
    risk_level?: string;
    action_type?: string;
    checked_at?: string;
}

export interface ITaskMetadata {
    source?: string;
    sourceUrl?: string;
    externalId?: string;
    type?: string;
    assignedAgent?: string;
    assignedBotUID?: string;
    acceptanceCriteria: string[];
    riskLevel?: string;
    relatedFiles: string[];
    prUrl?: string;
    verification?: ITaskVerificationMetadata;
    failure?: ITaskFailureMetadata;
    run?: ITaskRunMetadata;
    suggestions: ITaskSuggestionMetadata[];
    bypass?: ITaskBypassMetadata;
}

export function parseTaskMetadata(metadata: Record<string, string> | undefined): ITaskMetadata {
    return {
        source: nonEmpty(metadata?.[TASK_METADATA_KEYS.source]),
        sourceUrl: nonEmpty(metadata?.[TASK_METADATA_KEYS.sourceUrl]),
        externalId: nonEmpty(metadata?.[TASK_METADATA_KEYS.externalId]),
        type: nonEmpty(metadata?.[TASK_METADATA_KEYS.type]),
        assignedAgent: nonEmpty(metadata?.[TASK_METADATA_KEYS.assignedAgent]),
        assignedBotUID: nonEmpty(metadata?.[TASK_METADATA_KEYS.assignedBotUID]),
        acceptanceCriteria: parseStringList(metadata?.[TASK_METADATA_KEYS.acceptanceCriteria]),
        riskLevel: nonEmpty(metadata?.[TASK_METADATA_KEYS.riskLevel]),
        relatedFiles: parseStringList(metadata?.[TASK_METADATA_KEYS.relatedFiles]),
        prUrl: nonEmpty(metadata?.[TASK_METADATA_KEYS.prUrl]),
        verification: parseObject<ITaskVerificationMetadata>(metadata?.[SYSTEM_TASK_METADATA_KEYS.verification]),
        failure: parseFailure(metadata?.[SYSTEM_TASK_METADATA_KEYS.failure]),
        run: parseObject<ITaskRunMetadata>(metadata?.[SYSTEM_TASK_METADATA_KEYS.run]),
        suggestions: parseSuggestions(metadata?.[SYSTEM_TASK_METADATA_KEYS.suggestions]),
        bypass: parseObject<ITaskBypassMetadata>(metadata?.[SYSTEM_TASK_METADATA_KEYS.bypass]),
    };
}

export function hasTaskMetadata(task: ITaskMetadata): bool {
    return !!(
        task.source ||
        task.sourceUrl ||
        task.externalId ||
        task.type ||
        task.assignedAgent ||
        task.assignedBotUID ||
        task.acceptanceCriteria.length ||
        task.riskLevel ||
        task.relatedFiles.length ||
        task.prUrl ||
        task.verification ||
        task.failure ||
        task.run ||
        task.suggestions.length ||
        task.bypass
    );
}

export function formatTaskMetadataValue(value: string | undefined): string {
    if (!value) {
        return "";
    }

    return value
        .replace(/[_-]+/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .replace(/\b\w/g, (char) => char.toUpperCase());
}

function nonEmpty(value: string | undefined): string | undefined {
    const trimmed = value?.trim();
    return trimmed ? trimmed : undefined;
}

function parseObject<T extends object>(value: string | undefined): T | undefined {
    if (!value) {
        return undefined;
    }

    try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as T) : undefined;
    } catch {
        return undefined;
    }
}

function parseStringList(value: string | undefined): string[] {
    if (!value) {
        return [];
    }

    try {
        const parsed = JSON.parse(value);
        if (Array.isArray(parsed)) {
            return parsed.filter((item): item is string => typeof item === "string" && !!item.trim()).map((item) => item.trim());
        }
    } catch {
        return value
            .split("\n")
            .map((item) => item.trim())
            .filter(Boolean);
    }

    return [];
}

function parseFailure(value: string | undefined): ITaskFailureMetadata | undefined {
    const failure = parseObject<ITaskFailureMetadata>(value);
    if (!failure) {
        return undefined;
    }

    return {
        ...failure,
        reproduction: Array.isArray(failure.reproduction)
            ? failure.reproduction.filter((item): item is string => typeof item === "string" && !!item.trim())
            : [],
        recommendation: Array.isArray(failure.recommendation)
            ? failure.recommendation.filter((item): item is string => typeof item === "string" && !!item.trim())
            : [],
    };
}

function parseSuggestions(value: string | undefined): ITaskSuggestionMetadata[] {
    if (!value) {
        return [];
    }

    try {
        const parsed = JSON.parse(value);
        if (!Array.isArray(parsed)) {
            return [];
        }

        return parsed.filter((item): item is ITaskSuggestionMetadata => item && typeof item === "object" && !Array.isArray(item));
    } catch {
        return [];
    }
}
