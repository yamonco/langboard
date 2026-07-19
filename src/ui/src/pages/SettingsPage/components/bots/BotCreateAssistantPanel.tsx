import Badge from "@/components/base/Badge";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Textarea from "@/components/base/Textarea";
import Toast from "@/components/base/Toast";
import useDraftBotFromInstruction, { IBotDraft } from "@/controllers/api/settings/bots/useDraftBotFromInstruction";
import { Utils } from "@langboard/core/utils";
import { useState } from "react";
import { useTranslation } from "react-i18next";

interface IBotCreateAssistantPanelProps {
    disabled?: bool;
    getCurrentValue: () => Record<string, unknown>;
    onApplyDraft: (draft: IBotDraft) => void;
}

interface IBotCreateAssistantMessage {
    role: "user" | "assistant";
    content: string;
}

function BotCreateAssistantPanel({ disabled, getCurrentValue, onApplyDraft }: IBotCreateAssistantPanelProps): React.JSX.Element {
    const [t] = useTranslation();
    const [instruction, setInstruction] = useState("");
    const [messages, setMessages] = useState<IBotCreateAssistantMessage[]>([]);
    const { mutate, isPending } = useDraftBotFromInstruction({ interceptToast: true });
    const canSend = !!instruction.trim() && !disabled && !isPending;

    const submit = () => {
        const nextInstruction = instruction.trim();
        if (!canSend) {
            return;
        }

        const currentValue = getCurrentValue();
        const selectedApiNames = Utils.Type.isArray(currentValue["api_names"]) ? (currentValue["api_names"] as string[]) : [];
        const selectedComfortToolNames = Utils.Type.isArray(currentValue["comfort_tool_names"])
            ? (currentValue["comfort_tool_names"] as string[])
            : [];

        setMessages((prevMessages) => [...prevMessages, { role: "user", content: nextInstruction }]);
        setInstruction("");
        mutate(
            {
                instruction: nextInstruction,
                value: currentValue,
                selected_api_names: selectedApiNames,
                selected_comfort_tool_names: selectedComfortToolNames,
            },
            {
                onSuccess: (draft) => {
                    onApplyDraft(draft);
                    setMessages((prevMessages) => [
                        ...prevMessages,
                        {
                            role: "assistant",
                            content: t("bot.agent.Bot draft applied", { name: draft.bot_name }),
                        },
                    ]);
                    Toast.Add.success(t("successes.Bot draft applied."));
                },
            }
        );
    };

    return (
        <Box rounded border px="3" py="3" className="bg-muted/20">
            <Flex items="center" gap="2" mb="2">
                <Box className="rounded-full bg-primary/10 p-1.5 text-primary">
                    <IconComponent icon="bot" size="4" />
                </Box>
                <Box textSize="sm" weight="medium">
                    {t("bot.agent.Bot creation assistant")}
                </Box>
                <Badge variant="secondary" className="ml-auto px-1.5 py-0 text-[11px]">
                    {t("bot.agent.Draft only")}
                </Badge>
            </Flex>
            {messages.length ? (
                <Flex direction="col" gap="1.5" mb="2" className="max-h-40 overflow-y-auto">
                    {messages.map((message, index) => (
                        <Box
                            key={`bot-create-assistant-message-${index}`}
                            textSize="xs"
                            className={
                                message.role === "user"
                                    ? "ml-8 rounded-md bg-primary px-2 py-1.5 text-primary-foreground"
                                    : "mr-8 rounded-md border border-input bg-background px-2 py-1.5 text-muted-foreground"
                            }
                        >
                            {message.content}
                        </Box>
                    ))}
                </Flex>
            ) : null}
            <Textarea
                value={instruction}
                placeholder={t("bot.agent.Describe the bot to create")}
                rows={3}
                disabled={disabled || isPending}
                className="resize-none"
                onChange={(event) => setInstruction(event.currentTarget.value)}
            />
            <Flex justify="end" mt="2">
                <Button type="button" size="sm" className="gap-1.5" disabled={!canSend} onClick={submit}>
                    <IconComponent icon="send" size="3.5" />
                    {t("bot.agent.Create draft")}
                </Button>
            </Flex>
        </Box>
    );
}

export default BotCreateAssistantPanel;
