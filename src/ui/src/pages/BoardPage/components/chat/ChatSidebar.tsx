import { memo, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Conversation from "@/pages/BoardPage/components/chat/Conversation";
import ChatInput from "@/pages/BoardPage/components/chat/ChatInput";
import { CHAT_INPUT_MIN_HEIGHT } from "@/pages/BoardPage/components/chat/constants";
import ChatSessionList from "@/pages/BoardPage/components/chat/ChatSessionList";
import { cn } from "@/core/utils/ComponentUtils";
import ChatSessionMoreMenu from "@/pages/BoardPage/components/chat/ChatSessionMoreMenu";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { ChatSessionModel } from "@/core/models";
import { TDroppableAreaState } from "@/core/helpers/dnd/types";
import { DROPPABLE_AREA_IDLE } from "@/core/helpers/dnd/createDndDroppableAreaEvents";
import invariant from "tiny-invariant";
import { columnRowDndHelpers } from "@/core/helpers/dnd";
import { BOARD_DND_SETTINGS } from "@/pages/BoardPage/components/board/BoardConstants";
import { useBoardController } from "@/core/providers/BoardController";
import { isModel } from "@/core/models/ModelRegistry";
import { createBoardDroppableArea } from "@/pages/BoardPage/BoardUtils";
import { TChatScope } from "@langboard/core/types";

export interface IChatSidebarProps {
    ref: React.RefObject<HTMLDivElement | null>;
    onClose?: () => void;
    active?: bool;
}

const ChatSidebar = memo(({ ref, onClose, active = true }: IChatSidebarProps): React.JSX.Element => {
    const [t] = useTranslation();
    const { chatResizableSidebar } = useBoardController();
    const [state, setState] = useState<TDroppableAreaState>(DROPPABLE_AREA_IDLE);
    const { setSelectedScope, requestSessionList } = useBoardChat();

    useEffect(() => {
        if (active) requestSessionList();
    }, [active, requestSessionList]);

    useEffect(() => {
        const area = ref?.current;
        invariant(area);

        return columnRowDndHelpers.droppableArea({
            droppableAreas: createBoardDroppableArea({
                chatSidebarRef: ref,
                onDropInChatSidebar: (model) => {
                    let scopeType: TChatScope | undefined;
                    if (isModel(model, "ProjectColumn")) {
                        scopeType = "project_column";
                    } else if (isModel(model, "ProjectCard")) {
                        scopeType = "card";
                    } else if (isModel(model, "ProjectWiki")) {
                        scopeType = "project_wiki";
                    }

                    if (!scopeType) {
                        return;
                    }

                    setSelectedScope([scopeType, model.uid]);
                },
            }),
            settings: BOARD_DND_SETTINGS,
            setState,
        });
    }, [chatResizableSidebar, setSelectedScope]);

    return (
        <Flex direction="col" size="full" position="relative" ref={ref}>
            <Box
                position="absolute"
                size="full"
                top="0"
                left="0"
                className={cn(
                    "pointer-events-none bg-background/50 backdrop-blur-sm transition-all duration-200 ease-in-out",
                    state.type === "idle" ? "opacity-0" : "opacity-100"
                )}
                z={state.type === "idle" ? "-50" : "50"}
            >
                <Flex items="center" justify="center" size="full" textSize={{ initial: "lg", md: "xl" }} className="truncate text-nowrap">
                    {t("project.Drop here to add")}
                </Flex>
            </Box>
            <ChatSidebarDisplay onClose={onClose} />
        </Flex>
    );
});

function ChatSidebarDisplay({ onClose }: { onClose?: () => void }) {
    const [t] = useTranslation();
    const [height, setHeight] = useState(CHAT_INPUT_MIN_HEIGHT);
    const { isSessionListOpened } = useBoardChat();

    return (
        <>
            <Box position="relative" className="relative h-[calc(3rem+env(safe-area-inset-top))] shrink-0 border-b border-border/50">
                <Flex
                    items="center"
                    justify="center"
                    h="full"
                    textSize={{ initial: "base", md: "lg" }}
                    className="truncate text-nowrap pl-14 pr-24 text-sm font-medium md:px-14"
                >
                    {t("project.Chat with AI")}
                </Flex>
                <ChatSidebarSessionListButton />
                <ChatSessionMoreMenuButton hasCloseButton={!!onClose} />
                {onClose && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="absolute right-1 top-1/2 size-11 -translate-y-1/2"
                        data-workbench-context-close=""
                        aria-label={t("common.Close")}
                        onClick={onClose}
                    >
                        <IconComponent icon="x" size="5" />
                    </Button>
                )}
            </Box>
            <Flex position="relative" minH="0" className="flex-1 overflow-hidden">
                <ChatSessionList />
                <Box h="full" className={cn("flex min-h-0 w-full min-w-0 flex-col overflow-hidden", isSessionListOpened && "hidden")}>
                    <Conversation />
                    <ChatInput height={height} setHeight={setHeight} />
                </Box>
            </Flex>
        </>
    );
}

function ChatSidebarSessionListButton() {
    const { isSessionListOpened, setIsSessionListOpened } = useBoardChat();
    const [t] = useTranslation();

    const handleClick = () => {
        setIsSessionListOpened(!isSessionListOpened);
    };

    return (
        <Button
            variant="ghost"
            size="icon"
            className={cn("absolute left-1 top-1/2 size-11 -translate-y-1/2 transform", isSessionListOpened && "bg-accent/50")}
            aria-label={t("project.Session list")}
            aria-expanded={isSessionListOpened}
            title={t("project.Session list")}
            titleAlign="start"
            titleSide="bottom"
            onClick={handleClick}
        >
            <IconComponent icon="panel-left" size="5" />
        </Button>
    );
}

function ChatSessionMoreMenuButton({ hasCloseButton }: { hasCloseButton: boolean }) {
    const { currentSessionUID } = useBoardChat();
    const session = ChatSessionModel.Model.useModel((model) => model.uid === currentSessionUID, [currentSessionUID]);

    return (
        <ChatSessionMoreMenu
            icon="ellipsis-vertical"
            iconSize="5"
            menuButtonProps={{
                variant: "ghost",
                size: "icon",
                className: cn("absolute top-1/2 size-11 -translate-y-1/2 transform", hasCloseButton ? "right-12" : "right-1"),
            }}
            session={session}
        />
    );
}

export default ChatSidebar;
