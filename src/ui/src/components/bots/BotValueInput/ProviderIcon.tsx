import Kimi from "@/assets/svgs/icons/Kimi.png";
import LiteLLMDark from "@/assets/svgs/icons/LiteLLM-dark.png";
import LiteLLMLight from "@/assets/svgs/icons/LiteLLM-light.png";
import OpenRouterDark from "@/assets/svgs/icons/OpenRouter-dark.svg";
import OpenRouterLight from "@/assets/svgs/icons/OpenRouter-light.svg";
import ZAI from "@/assets/svgs/icons/ZAI.svg";
import IconComponent from "@/components/base/IconComponent";
import { providerIconMap } from "@/components/bots/BotValueInput/utils";
import { TAgentModelName } from "@langboard/core/ai";
import { useTheme } from "next-themes";

const ProviderIcon = ({ provider }: { provider: TAgentModelName }) => {
    const { resolvedTheme } = useTheme();
    const dark = resolvedTheme === "dark";
    const source =
        provider === "Z.ai" || provider === "Z.ai Coding Plan"
            ? ZAI
            : provider === "OpenRouter"
              ? dark
                  ? OpenRouterDark
                  : OpenRouterLight
              : provider === "LiteLLM"
                ? dark
                    ? LiteLLMDark
                    : LiteLLMLight
                : provider === "Kimi"
                  ? Kimi
                  : undefined;

    return source ? (
        <img src={source} alt="" aria-hidden="true" className="size-4 shrink-0 object-contain" />
    ) : (
        <IconComponent icon={providerIconMap[provider]} size="4" />
    );
};

export default ProviderIcon;
