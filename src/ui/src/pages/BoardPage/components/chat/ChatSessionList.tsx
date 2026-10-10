import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import { ChatSessionModel } from "@/core/models";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { cn } from "@/core/utils/ComponentUtils";
import ChatSessionMoreMenu from "@/pages/BoardPage/components/chat/ChatSessionMoreMenu";
import { useTranslation } from "react-i18next";

function ChatSessionList(): React.JSX.Element {
    const [t] = useTranslation();
    const { chatSessions, setCurrentSessionUID, isSessionListOpened, setIsSessionListOpened } = useBoardChat();

    const handleClickNewChat = () => {
        setCurrentSessionUID(undefined);
        setIsSessionListOpened(false);
    };

    return (
        <Box w="full" h="full" className={cn("min-w-0 bg-background p-2", !isSessionListOpened && "hidden")}>
            <Button
                size="sm"
                variant="ghost"
                className={cn(
                    "mb-2 ml-2 mr-1 w-[calc(100%_-_theme(spacing.4)_-_1px)] justify-start gap-2",
                    !isSessionListOpened && "hidden"
                )}
                onClick={handleClickNewChat}
            >
                <IconComponent icon="square-pen" size="4" />
                {t("project.New chat")}
            </Button>
            <Box w="full" className={cn("h-[calc(100%_-_theme(spacing.12))] overflow-y-auto pl-2 pr-1", !isSessionListOpened && "hidden")}>
                {chatSessions.map((session) => (
                    <ChatSession key={`chat-session-${session.uid}`} session={session} />
                ))}
            </Box>
        </Box>
    );
}

function ChatSession({ session }: { session: ChatSessionModel.TModel }) {
    const [t] = useTranslation();
    const { currentSessionUID, setCurrentSessionUID, setIsSessionListOpened } = useBoardChat();
    const title = session.useField("title");

    const handleClick = () => {
        setCurrentSessionUID(session.uid);
        setIsSessionListOpened(false);
    };

    return (
        <Flex
            items="center"
            justify="between"
            w="full"
            h="11"
            rounded="md"
            pl="2"
            textSize="xs"
            cursor="pointer"
            position="relative"
            className={cn("truncate transition-colors", currentSessionUID === session.uid && "bg-accent/50")}
        >
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <button
                        type="button"
                        aria-current={currentSessionUID === session.uid ? "true" : undefined}
                        className="peer relative z-10 h-full w-[calc(100%_-_theme(spacing.8))] truncate py-2 text-left text-sm hover:text-accent-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring"
                        onClick={handleClick}
                    >
                        {title || t("project.Untitled")}
                    </button>
                </Tooltip.Trigger>
                <Tooltip.Content align="start" side="bottom">
                    {title || t("project.Untitled")}
                </Tooltip.Content>
            </Tooltip.Root>
            <Box position="absolute" top="0" left="0" w="full" h="full" rounded="md" className="hidden bg-accent peer-hover:block" />
            <ChatSessionMoreMenu
                icon="ellipsis"
                iconSize="4"
                menuButtonProps={{
                    variant: "ghost",
                    size: "icon-sm",
                    className: "relative z-10",
                }}
                session={session}
            />
        </Flex>
    );
}

export default ChatSessionList;
