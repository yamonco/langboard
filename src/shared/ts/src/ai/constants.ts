export enum EBotPlatform {
    Default = "default",
    Langflow = "langflow",
    N8N = "n8n",
}

export enum EBotPlatformRunningType {
    Default = "default",
    Endpoint = "endpoint",
}

export const AVAILABLE_RUNNING_TYPES_BY_PLATFORM: Record<EBotPlatform, EBotPlatformRunningType[]> = {
    [EBotPlatform.Default]: [EBotPlatformRunningType.Default],
    [EBotPlatform.Langflow]: [EBotPlatformRunningType.Endpoint],
    [EBotPlatform.N8N]: [EBotPlatformRunningType.Default],
};

export const ALLOWED_ALL_IPS_BY_PLATFORMS: Record<EBotPlatform, EBotPlatformRunningType[]> = {
    [EBotPlatform.Default]: [EBotPlatformRunningType.Default],
    [EBotPlatform.Langflow]: [],
    [EBotPlatform.N8N]: [EBotPlatformRunningType.Default],
};

export const AGENT_MODELS = [
    "OpenAI",
    "OpenAI Compatible",
    "Z.ai Coding Plan",
    "OpenRouter",
    "LiteLLM",
    "Kimi",
    "Azure OpenAI",
    "Groq",
    "Anthropic",
    "NVIDIA",
    "IBM Watson",
    "Amazon Bedrock",
    "Google Generative AI",
    "SambaNova",
    "Ollama",
    "LM Studio",
] as const;

export type TAgentModelName = (typeof AGENT_MODELS)[number];

export enum EApiPermission {
    Read = "read",
    Create = "create",
    Edit = "edit",
    Delete = "delete",
}

export enum EAgentPermissionLevel {
    Read = "read",
    Edit = "edit",
    FullAccess = "full_access",
}

export enum EAgentApprovalPolicy {
    Allow = "allow",
    Ask = "ask",
    Deny = "deny",
}

export const AGENT_PERMISSION_LEVEL_PERMISSIONS: Record<EAgentPermissionLevel, EApiPermission[]> = {
    [EAgentPermissionLevel.Read]: [EApiPermission.Read],
    [EAgentPermissionLevel.Edit]: [EApiPermission.Read, EApiPermission.Create, EApiPermission.Edit],
    [EAgentPermissionLevel.FullAccess]: [EApiPermission.Read, EApiPermission.Create, EApiPermission.Edit, EApiPermission.Delete],
};

export const AGENT_PERMISSION_LEVEL_APPROVAL_POLICY: Record<EAgentPermissionLevel, Partial<Record<EApiPermission, EAgentApprovalPolicy>>> = {
    [EAgentPermissionLevel.Read]: {
        [EApiPermission.Read]: EAgentApprovalPolicy.Allow,
    },
    [EAgentPermissionLevel.Edit]: {
        [EApiPermission.Read]: EAgentApprovalPolicy.Allow,
        [EApiPermission.Create]: EAgentApprovalPolicy.Ask,
        [EApiPermission.Edit]: EAgentApprovalPolicy.Ask,
    },
    [EAgentPermissionLevel.FullAccess]: {
        [EApiPermission.Read]: EAgentApprovalPolicy.Allow,
        [EApiPermission.Create]: EAgentApprovalPolicy.Ask,
        [EApiPermission.Edit]: EAgentApprovalPolicy.Ask,
        [EApiPermission.Delete]: EAgentApprovalPolicy.Ask,
    },
};

export const OPENAI_COMPATIBLE_PROVIDERS = {
    OpenAI: "https://api.openai.com/v1",
    "OpenAI Compatible": "",
    "Z.ai Coding Plan": "https://api.z.ai/api/coding/paas/v4",
    OpenRouter: "https://openrouter.ai/api/v1",
    LiteLLM: "",
    Kimi: "https://api.moonshot.ai/v1",
} as const;
