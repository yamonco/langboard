import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import useGetProjectChatMessages from "@/controllers/api/board/chat/useGetProjectChatMessages";
import Box from "@/components/base/Box";
import Loading from "@/components/base/Loading";
import { useBoardChat } from "@/core/providers/BoardChatProvider";
import { ChatMessageList } from "@/components/Chat/ChatMessageList";
import { ChatMessageModel } from "@/core/models";
import ChatMessage from "@/pages/BoardPage/components/chat/ChatMessage";

const LOADING_ELEMENT_MIDDLE_Y = 18;

function Conversation(): React.JSX.Element {
    const { projectUID, scrollToBottomRef, isAtBottomRef, currentSessionUID } = useBoardChat();
    const [t] = useTranslation();
    const [isLoaded, setIsLoaded] = useState(false);
    const isFetchingRef = useRef(false);
    const [isFetched, setIsFetched] = useState(false);
    const { mutateAsync, isLastPage, setIsLastPage, pageRef, lastCurrentDateRef, lastPagesRef } = useGetProjectChatMessages(projectUID);
    const messages = ChatMessageModel.Model.useModels(
        (model) => !!currentSessionUID && model.chat_session_uid === currentSessionUID,
        [currentSessionUID]
    );
    const conversationRef = useRef<HTMLDivElement>(null);
    const sortedMessages = useMemo(() => messages.sort((a, b) => a.updated_at.getTime() - b.updated_at.getTime()), [messages]);
    const lastChatListHeightRef = useRef(0);

    const nextPage = async () => {
        if (isFetchingRef.current || isLastPage) {
            return;
        }

        isFetchingRef.current = true;
        try {
            await mutateAsync({ session_uid: currentSessionUID });
        } finally {
            isFetchingRef.current = false;
        }
    };

    useEffect(() => {
        if (!currentSessionUID) {
            setIsLastPage(true);
            return;
        }

        if (!lastPagesRef.current[currentSessionUID]) {
            lastPagesRef.current[currentSessionUID] = 0;
        }

        pageRef.current = lastPagesRef.current[currentSessionUID];
        if (pageRef.current) {
            return;
        }

        lastCurrentDateRef.current = new Date();
        mutateAsync({
            session_uid: currentSessionUID,
        });

        return () => {
            pageRef.current = 0;
        };
    }, [currentSessionUID]);

    useEffect(() => {
        if (!conversationRef.current) {
            return;
        }

        const onScroll = async () => {
            if (!isLoaded) {
                setIsLoaded(true);
                return;
            }

            if (isLastPage) {
                return;
            }

            if (isFetchingRef.current) {
                lastChatListHeightRef.current = conversationRef.current!.scrollHeight;
                return;
            }

            lastChatListHeightRef.current = conversationRef.current!.scrollHeight;
            if (conversationRef.current!.scrollTop <= LOADING_ELEMENT_MIDDLE_Y) {
                try {
                    await nextPage();
                    setIsFetched(true);
                } catch {
                    // The API error handler reports the failure; the next scroll can retry.
                    setIsFetched(false);
                }
            }
        };

        conversationRef.current.addEventListener("scroll", onScroll);

        return () => {
            conversationRef.current?.removeEventListener("scroll", onScroll);
        };
    }, [isLoaded, isLastPage, currentSessionUID]);

    useEffect(() => {
        if (
            !isFetched ||
            !conversationRef.current ||
            !lastChatListHeightRef.current ||
            conversationRef.current.scrollHeight === lastChatListHeightRef.current
        ) {
            return;
        }

        conversationRef.current.scrollTop = conversationRef.current.scrollHeight - lastChatListHeightRef.current;
        lastChatListHeightRef.current = 0;
        setIsFetched(false);
    }, [isFetched]);

    return (
        <Box className="min-h-0 flex-1">
            <ChatMessageList
                className="overscroll-contain bg-background"
                scrollToBottomRef={scrollToBottomRef}
                isAtBottomRef={isAtBottomRef}
                ref={conversationRef}
            >
                {!isLastPage && <Loading size="3" variant="secondary" spacing="1" animate="bounce" my="3" />}
                {sortedMessages.map((chatMessage) => (
                    <ChatMessage key={`chat-bubble-${chatMessage.uid}`} chatMessage={chatMessage} />
                ))}
                {!messages.length && (
                    <Box mx="auto" mt="8" w="full" px="4" py="6" className="max-w-md text-center text-muted-foreground">
                        <h2 className="text-sm font-medium leading-relaxed">{t("project.Ask anything to {app} AI!")}</h2>
                    </Box>
                )}
            </ChatMessageList>
        </Box>
    );
}

export default Conversation;
