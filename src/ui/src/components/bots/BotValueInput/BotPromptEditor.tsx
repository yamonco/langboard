import Box from "@/components/base/Box";
import Label from "@/components/base/Label";
import { PlateEditor } from "@/components/Editor/plate-editor";
import { AuthUser } from "@/core/models";
import { useTranslation } from "react-i18next";

interface IBotPromptEditorProps {
    currentUser: AuthUser.TModel;
    value: string;
    disabled?: bool;
    isValidating?: bool;
    inputRef?: (element: HTMLElement | null) => void;
    resetKey: number;
    onValueChange: (value: string) => void;
}

const normalizePromptValue = (value: string) => {
    const cleanValue = value.replace(/\u200B/g, "");
    return cleanValue.trim() ? cleanValue : "";
};

const BOT_PROMPT_EDITOR_CONTAINER_CLASS_NAME = [
    "rounded-md border border-input bg-background overflow-x-hidden",
    "[&_[role=toolbar]]:max-w-full",
    "[&_[role=toolbar]]:overflow-x-auto",
    "[&_[role=toolbar]]:overflow-y-hidden",
    "[&_[role=toolbar]]:[scrollbar-width:thin]",
    "[&_[role=toolbar]>div]:min-w-max",
].join(" ");

function BotPromptEditor({
    currentUser,
    value,
    disabled,
    isValidating,
    inputRef,
    resetKey,
    onValueChange,
}: IBotPromptEditorProps): React.JSX.Element {
    const [t] = useTranslation();
    const readOnly = !!disabled || !!isValidating;
    const editorProps = {
        currentUser,
        mentionables: [],
        linkables: [],
        value: {
            content: value || "",
        },
        setValue: (nextValue: { content: string }) => onValueChange(normalizePromptValue(nextValue.content)),
        readOnly,
        variant: "ai" as const,
        placeholder: t("bot.agent.System prompt"),
        className: "min-h-36 px-3 py-2 text-sm",
        containerClassName: BOT_PROMPT_EDITOR_CONTAINER_CLASS_NAME,
        editorComponentRef: inputRef,
    };

    return (
        <Box>
            <Label display="block" mb="1" textSize="sm" className="font-medium">
                {t("bot.agent.System prompt")}
            </Label>
            <PlateEditor key={`bot-prompt-editor-${resetKey}`} {...editorProps} editorType="view" form={{}} />
        </Box>
    );
}

export default BotPromptEditor;
