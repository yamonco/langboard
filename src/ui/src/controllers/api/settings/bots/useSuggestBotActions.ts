import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";

export type TBotActionSuggestionSource = "comfort_tool" | "api" | "mcp_tool" | "mcp_tool_group";
export type TBotActionSuggestionRisk = "low" | "medium" | "high";

export interface IBotActionSuggestion {
    source: TBotActionSuggestionSource;
    name: string;
    label: string;
    description: string;
    api_names: string[];
    risk: TBotActionSuggestionRisk;
    confidence: number;
    already_selected: bool;
    reason: string;
}

export interface IBotActionSuggestionForm {
    prompt: string;
    selected_api_names: string[];
    selected_comfort_tool_names: string[];
    include_mcp?: bool;
    limit?: number;
}

const useSuggestBotActions = (options?: TMutationOptions<IBotActionSuggestionForm, IBotActionSuggestion[]>) => {
    const { mutate } = useQueryMutation();

    const suggestBotActions = async (form: IBotActionSuggestionForm) => {
        const res = await api.post(Routing.API.SETTINGS.BOTS.ACTION_SUGGESTIONS, form, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return (res.data.suggestions ?? []) as IBotActionSuggestion[];
    };

    const result = mutate(["suggest-bot-actions"], suggestBotActions, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useSuggestBotActions;
