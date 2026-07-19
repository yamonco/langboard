import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import useSuggestBotActions, { type IBotActionSuggestion } from "@/controllers/api/settings/bots/useSuggestBotActions";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

interface IBotActionSuggestionPanelProps {
    prompt: string;
    selectedApis: string[];
    selectedComfortTools: string[];
    initialSuggestions?: IBotActionSuggestion[];
    disabled?: bool;
    onApplySuggestion: (suggestion: IBotActionSuggestion) => void;
}

const riskVariantMap = {
    low: "secondary",
    medium: "outline",
    high: "destructive",
} as const;

function BotActionSuggestionPanel({
    prompt,
    selectedApis,
    selectedComfortTools,
    initialSuggestions,
    disabled,
    onApplySuggestion,
}: IBotActionSuggestionPanelProps): React.JSX.Element {
    const [t] = useTranslation();
    const [suggestions, setSuggestions] = useState<IBotActionSuggestion[]>(initialSuggestions ?? []);
    const { mutate, isPending } = useSuggestBotActions({ interceptToast: true });
    const hasPrompt = !!prompt.trim();

    useEffect(() => {
        setSuggestions(initialSuggestions ?? []);
    }, [initialSuggestions]);

    const requestSuggestions = () => {
        if (!hasPrompt || disabled || isPending) {
            return;
        }

        mutate(
            {
                prompt,
                selected_api_names: selectedApis,
                selected_comfort_tool_names: selectedComfortTools,
                limit: 8,
            },
            {
                onSuccess: setSuggestions,
            }
        );
    };

    return (
        <Box mt="2">
            <Flex items="center" justify="between" gap="2">
                <Box textSize="xs" className="text-muted-foreground">
                    {t("bot.agent.Action suggestion help")}
                </Box>
                <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 shrink-0 gap-1.5 px-2.5"
                    disabled={!hasPrompt || disabled || isPending}
                    onClick={requestSuggestions}
                >
                    <IconComponent icon="wand-sparkles" size="3.5" />
                    {t("bot.agent.Add actions from prompt")}
                </Button>
            </Flex>
            {suggestions.length ? (
                <Flex direction="col" gap="1.5" mt="2">
                    {suggestions.map((suggestion) => {
                        const canApply = suggestion.source === "comfort_tool" || suggestion.source === "api";
                        const isSelected =
                            suggestion.source === "comfort_tool"
                                ? selectedComfortTools.includes(suggestion.name)
                                : suggestion.source === "api" && selectedApis.includes(suggestion.name);
                        let buttonLabel = "bot.agent.Apply action";
                        if (!canApply) {
                            buttonLabel = "bot.agent.Review action";
                        } else if (isSelected) {
                            buttonLabel = "bot.agent.Applied";
                        }

                        return (
                            <Flex
                                key={`bot-action-suggestion-${suggestion.source}-${suggestion.name}`}
                                items="start"
                                justify="between"
                                gap="2"
                                className="rounded-md border border-input bg-muted/20 px-3 py-2"
                            >
                                <Box className="min-w-0 flex-1">
                                    <Flex items="center" gap="1.5" wrap>
                                        <Box textSize="sm" weight="medium" className="truncate">
                                            {suggestion.label}
                                        </Box>
                                        <Badge variant="secondary" className="px-1.5 py-0 text-[11px]">
                                            {t(`bot.agent.actionSuggestionSources.${suggestion.source}`)}
                                        </Badge>
                                        <Badge variant={riskVariantMap[suggestion.risk]} className="px-1.5 py-0 text-[11px]">
                                            {t(`bot.agent.actionSuggestionRisks.${suggestion.risk}`)}
                                        </Badge>
                                    </Flex>
                                    <Box textSize="xs" className="mt-1 line-clamp-2 text-muted-foreground">
                                        {suggestion.reason}
                                    </Box>
                                </Box>
                                <Tooltip.Root>
                                    <Tooltip.Trigger asChild>
                                        <Button
                                            type="button"
                                            size="sm"
                                            variant={isSelected ? "secondary" : "default"}
                                            className="h-7 shrink-0 px-2"
                                            disabled={disabled || isSelected || !canApply}
                                            onClick={() => {
                                                if (!canApply) {
                                                    return;
                                                }

                                                onApplySuggestion(suggestion);
                                            }}
                                        >
                                            {t(buttonLabel)}
                                        </Button>
                                    </Tooltip.Trigger>
                                    <Tooltip.Content className="max-w-[min(95vw,theme(spacing.96))]">
                                        <Box>{suggestion.description}</Box>
                                        {suggestion.api_names.length ? (
                                            <Box mt="1" textSize="xs" className="text-muted-foreground">
                                                {suggestion.api_names.join(", ")}
                                            </Box>
                                        ) : null}
                                    </Tooltip.Content>
                                </Tooltip.Root>
                            </Flex>
                        );
                    })}
                </Flex>
            ) : null}
        </Box>
    );
}

export default BotActionSuggestionPanel;
