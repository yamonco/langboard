import { EBotPlatform, EBotPlatformRunningType } from "@langboard/core/ai";
import { TEditorCollaborationType } from "@langboard/core/constants";
import { AuthUser } from "@/core/models";
import type { IBotActionSuggestion } from "@/controllers/api/settings/bots/useSuggestBotActions";

export type TBotValueInputType = "default" | "text" | "json" | "none";

export type TBotValueDefaultInputRefLike = {
    type: "default-bot-json";
    value: string;
    syncValue: () => void;
    validate: (shouldFocus?: bool) => bool;
    onSuccess: () => void;
    patchValue: (value: Record<string, unknown>) => void;
};

export type TSharedBotValueInputProps = Omit<IBotValueInputProps, "valueType">;

export interface IBotValueInputProps {
    collaborationType?: TEditorCollaborationType;
    currentUser: AuthUser.TModel;
    platform: EBotPlatform;
    platformRunningType: EBotPlatformRunningType;
    section?: number | string;
    uid?: number | string;
    value: string;
    valueType: TBotValueInputType;
    newValueRef: React.RefObject<string>;
    isValidating: bool;
    disabled?: bool;
    isEditing?: bool;
    startEditing?: () => void;
    cancelEditing?: () => void;
    previewByDialog?: bool;
    initialActionSuggestions?: IBotActionSuggestion[];
    change?: () => void;
    required?: bool;
    label: string;
    ref?: React.Ref<HTMLInputElement | HTMLTextAreaElement | TBotValueDefaultInputRefLike>;
}
