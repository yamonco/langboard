import { useTranslation } from "react-i18next";
import * as React from "react";
import { ArrowDown } from "lucide-react";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import { useAutoScroll } from "@/core/hooks/useAutoScroll";
import { cn } from "@/core/utils/ComponentUtils";
import { Utils } from "@langboard/core/utils";

interface ChatMessageListProps extends React.HTMLAttributes<HTMLDivElement> {
    smooth?: bool;
    scrollToBottomRef?: React.RefObject<() => void>;
    isAtBottomRef?: React.RefObject<bool>;
}

const ChatMessageList = React.forwardRef<HTMLDivElement, ChatMessageListProps>(
    ({ className, children, smooth = false, scrollToBottomRef, isAtBottomRef, ...props }, ref) => {
        const [t] = useTranslation();
        const { scrollRef, isAtBottom, scrollToBottom, disableAutoScroll } = useAutoScroll({
            smooth,
            content: children,
        });

        if (scrollToBottomRef) {
            scrollToBottomRef.current = scrollToBottom;
        }

        if (isAtBottomRef) {
            isAtBottomRef.current = isAtBottom;
        }

        return (
            <Box position="relative" size="full" className="min-h-0 bg-gradient-to-b from-background via-muted/20 to-background">
                <Flex
                    size="full"
                    direction="col"
                    p={{
                        initial: "3",
                        md: "4",
                    }}
                    className={cn("min-h-0 overflow-y-auto", className)}
                    ref={(el) => {
                        scrollRef.current = el;
                        if (Utils.Type.isFunction(ref)) {
                            ref(el);
                        } else if (Utils.Type.isObject<React.RefObject<HTMLDivElement | null>>(ref)) {
                            ref.current = el;
                        }
                    }}
                    onWheel={disableAutoScroll}
                    onTouchMove={disableAutoScroll}
                    {...props}
                >
                    <Flex direction="col" gap="4" w="full" minW="0">
                        {children}
                    </Flex>
                </Flex>

                {!isAtBottom && (
                    <Button
                        onClick={() => {
                            scrollToBottom();
                        }}
                        size="icon"
                        variant="outline"
                        className="absolute bottom-2 left-1/2 inline-flex -translate-x-1/2 transform rounded-full shadow-md"
                        aria-label={t("common.Scroll to bottom")}
                    >
                        <ArrowDown className="size-4" />
                    </Button>
                )}
            </Box>
        );
    }
);

ChatMessageList.displayName = "ChatMessageList";

export { ChatMessageList };
