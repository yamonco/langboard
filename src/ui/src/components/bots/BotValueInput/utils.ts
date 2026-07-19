import { TSVGIconMap } from "@/assets/svgs/icons";
import { TBotValueDefaultInputRefLike, TBotValueInputType } from "@/components/bots/BotValueInput/types";
import { EBotPlatform, EBotPlatformRunningType, TAgentModelName } from "@langboard/core/ai";

type TBotValueInputRefLike = HTMLInputElement | HTMLTextAreaElement | TBotValueDefaultInputRefLike | null;

const waitForNextAnimationFrame = () => new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));

const isBotValueDefaultInputRef = (input: TBotValueInputRefLike): input is TBotValueDefaultInputRefLike => input?.type === "default-bot-json";

export const syncPendingBotValueInputChange = async (input: TBotValueInputRefLike) => {
    await waitForNextAnimationFrame();

    if (isBotValueDefaultInputRef(input)) {
        input.syncValue();
    }
};

export const getValueType = (platform: EBotPlatform, runningType: EBotPlatformRunningType): TBotValueInputType => {
    if (platform === EBotPlatform.Default) {
        if (runningType === EBotPlatformRunningType.Default) {
            return "default";
        }
    }

    if (platform === EBotPlatform.N8N) {
        if (runningType === EBotPlatformRunningType.Default) {
            return "default";
        }
    }

    return "text";
};

export const requirements: Partial<Record<EBotPlatform, Partial<Record<EBotPlatformRunningType, ("url" | "apiKey" | "value")[]>>>> = {
    [EBotPlatform.Default]: {
        [EBotPlatformRunningType.Default]: ["value"],
    },
    [EBotPlatform.Langflow]: {
        [EBotPlatformRunningType.Endpoint]: ["url", "apiKey", "value"],
    },
    [EBotPlatform.N8N]: {
        [EBotPlatformRunningType.Default]: ["url", "apiKey", "value"],
    },
};

export const showableDefaultInputs: Partial<Record<EBotPlatform, Partial<Record<EBotPlatformRunningType, ("api_names" | "provider" | "prompt")[]>>>> =
    {
        [EBotPlatform.Default]: {
            [EBotPlatformRunningType.Default]: ["api_names", "provider", "prompt"],
        },
        [EBotPlatform.N8N]: {
            [EBotPlatformRunningType.Default]: [],
        },
    };

export const providerIconMap: Record<TAgentModelName, keyof TSVGIconMap> = {
    OpenAI: "OpenAI",
    "Azure OpenAI": "Azure",
    Groq: "Groq",
    Anthropic: "Anthropic",
    "IBM Watson": "IBMWatson",
    NVIDIA: "Nvidia",
    "Amazon Bedrock": "AWS",
    "Google Generative AI": "GoogleGenerativeAI",
    SambaNova: "SambaNova",
    Ollama: "Ollama",
    "LM Studio": "LMStudio",
};
