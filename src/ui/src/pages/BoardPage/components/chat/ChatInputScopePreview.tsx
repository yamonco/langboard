/* eslint-disable @typescript-eslint/no-explicit-any */
import Badge from "@/components/base/Badge";
import Flex from "@/components/base/Flex";
import Tooltip from "@/components/base/Tooltip";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { useMemo } from "react";
import { ProjectCard, ProjectColumn, ProjectWiki } from "@/core/models";
import { useTranslation } from "react-i18next";

export interface IChatInputScopePreviewProps {
    scope: ProjectCard.TModel | ProjectColumn.TModel | ProjectWiki.TModel;
}

function ChatInputScopePreview({ scope }: IChatInputScopePreviewProps) {
    const { lockedScope, selectedScope } = useBoardChat();
    const [t] = useTranslation();
    const [scopeField, scopeBadge] = useMemo(() => {
        const [scopeTable] = lockedScope ?? selectedScope ?? [undefined, undefined];
        switch (scopeTable) {
            case "card":
                return ["title", scopeTable];
            case "project_column":
                return ["name", scopeTable];
            case "project_wiki":
                return ["title", scopeTable];
            default:
                return ["uid", "Unknown"];
        }
    }, [lockedScope, selectedScope, scope]);
    const scopeName: string = (scope as any).useField(scopeField);

    return (
        <Flex direction="col" justify="center" items="center" gap="1" size="full" className="min-w-0 overflow-hidden">
            <Flex
                direction="col"
                items="center"
                justify="center"
                className="min-w-0 overflow-hidden border-border text-center"
                w="full"
                h="20"
                border
                rounded="md"
            >
                <Badge variant="secondary">{t(`project.chatScopes.${scopeBadge}`)}</Badge>
                <Tooltip.Root>
                    <Tooltip.Trigger className="block min-w-0 max-w-full px-2">
                        <span className="block max-w-full truncate">{scopeName}</span>
                    </Tooltip.Trigger>
                    <Tooltip.Content align="center" side="top">
                        {scopeName}
                    </Tooltip.Content>
                </Tooltip.Root>
            </Flex>
        </Flex>
    );
}

export default ChatInputScopePreview;
