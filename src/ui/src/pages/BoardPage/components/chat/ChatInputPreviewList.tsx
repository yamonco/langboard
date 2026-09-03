import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { cn } from "@/core/utils/ComponentUtils";
import { useMemo } from "react";
import { ProjectCard, ProjectColumn, ProjectWiki } from "@/core/models";
import ChatInputScopePreview from "@/pages/BoardPage/components/chat/ChatInputScopePreview";
import { useChatInput } from "@/pages/BoardPage/components/chat/ChatInputProvider";
import ChatInputFilePreview from "@/pages/BoardPage/components/chat/ChatInputFilePreview";

function ChatInputPreviewList() {
    const { isSending, selectedScope, setSelectedScope, lockedScope } = useBoardChat();
    const { clearAttachmentPreview, file } = useChatInput();
    const effectiveScope = lockedScope ?? selectedScope;
    const isLockedScope = !!lockedScope;
    const scope = useMemo(() => {
        const [scopeTable, scopeUID] = effectiveScope || [undefined, undefined];
        if (!scopeTable || !scopeUID) {
            return null;
        }

        switch (scopeTable) {
            case "card":
                return ProjectCard.Model.getModel(scopeUID) || null;
            case "project_column":
                return ProjectColumn.Model.getModel(scopeUID) || null;
            case "project_wiki":
                return ProjectWiki.Model.getModel(scopeUID) || null;
            default:
                return null;
        }
    }, [effectiveScope]);

    if (!file && !effectiveScope) {
        return null;
    }

    return (
        <Flex w="full" gap="2" px="2" pt="2" className="min-w-0">
            <Flex position="relative" size="24" className={cn("shrink-0", !file && "hidden")}>
                {!isSending && (
                    <Button
                        type="button"
                        variant="destructive-ghost"
                        size="icon-sm"
                        className="absolute -right-3 -top-0.5 size-6"
                        onClick={clearAttachmentPreview}
                    >
                        <IconComponent icon="x" size="4" />
                    </Button>
                )}
                {file && <ChatInputFilePreview file={file} />}
            </Flex>
            <Flex position="relative" h="24" className={cn("min-w-0 flex-1", !effectiveScope && "hidden")}>
                {!isSending && !isLockedScope && (
                    <Button
                        type="button"
                        variant="destructive-ghost"
                        size="icon-sm"
                        className="absolute -right-3 -top-0.5 size-6"
                        onClick={() => setSelectedScope(undefined)}
                    >
                        <IconComponent icon="x" size="4" />
                    </Button>
                )}
                {scope && <ChatInputScopePreview key={`scope-${scope.MODEL_NAME}-${scope.uid}`} scope={scope} />}
            </Flex>
        </Flex>
    );
}

export default ChatInputPreviewList;
