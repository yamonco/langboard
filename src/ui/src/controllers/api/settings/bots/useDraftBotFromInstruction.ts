import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { IBotActionSuggestion } from "@/controllers/api/settings/bots/useSuggestBotActions";

export interface IBotDraftForm {
    instruction: string;
    value: Record<string, unknown>;
    selected_api_names: string[];
    selected_comfort_tool_names: string[];
    include_mcp?: bool;
}

export interface IBotDraft {
    bot_name: string;
    bot_uname: string;
    value_patch: Record<string, unknown>;
    suggestions: IBotActionSuggestion[];
}

const useDraftBotFromInstruction = (options?: TMutationOptions<IBotDraftForm, IBotDraft>) => {
    const { mutate } = useQueryMutation();

    const draftBotFromInstruction = async (form: IBotDraftForm) => {
        const res = await api.post(Routing.API.SETTINGS.BOTS.DRAFT, form, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        return res.data.draft as IBotDraft;
    };

    const result = mutate(["draft-bot-from-instruction"], draftBotFromInstruction, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useDraftBotFromInstruction;
