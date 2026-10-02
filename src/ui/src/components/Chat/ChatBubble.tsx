import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cva, type VariantProps } from "class-variance-authority";
import Avatar from "@/components/base/Avatar";
import Button, { type ButtonProps } from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import MessageLoading from "@/components/Chat/MessageLoading";
import { cn, copyToClipboard } from "@/core/utils/ComponentUtils";
import Markdown from "@/components/Markdown";
import { IChatContent } from "@/core/models/Base";
import { useTranslation } from "react-i18next";

// ChatBubble
const chatBubbleVariant = cva("group relative flex min-w-0 max-w-full gap-3", {
    variants: {
        variant: {
            received: "mr-auto max-w-[88%] items-start self-start",
            sent: "ml-auto min-w-0 max-w-[88%] flex-row-reverse items-start self-end",
        },
        layout: {
            default: "",
            ai: "max-w-full w-full items-center",
        },
    },
    defaultVariants: {
        variant: "received",
        layout: "default",
    },
});

interface ChatBubbleProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof chatBubbleVariant> {
    message?: IChatContent;
}

const ChatBubble = React.forwardRef<HTMLDivElement, ChatBubbleProps>(({ className, variant, layout, message, children, ...props }, ref) => (
    <div className={cn(chatBubbleVariant({ variant, layout, className }), "group relative")} ref={ref} {...props}>
        {React.Children.map(children, (child) =>
            React.isValidElement(child) && typeof child.type !== "string"
                ? React.cloneElement(child, {
                      variant,
                      layout,
                  } as React.ComponentProps<typeof child.type>)
                : child
        )}
        {!!message?.content && (
            <div className={cn("invisible absolute top-1 z-20 group-hover:visible", variant === "sent" ? "-left-8" : "right-1")}>
                <ChatBubbleCopyButton message={message} />
            </div>
        )}
    </div>
));
ChatBubble.displayName = "ChatBubble";

// ChatBubbleAvatar
interface ChatBubbleAvatarProps {
    src?: string;
    fallback?: React.ReactNode | string;
    title?: string;
    titleSide?: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>["side"];
    titleAlign?: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>["align"];
    className?: string;
}

const ChatBubbleAvatar: React.FC<ChatBubbleAvatarProps> = ({ src, fallback, title, titleAlign, titleSide, className }) => {
    const [t] = useTranslation();
    const avatar = (
        <Avatar.Root className={className}>
            <Avatar.Image src={src} alt={t("common.Avatar")} />
            <Avatar.Fallback>{fallback}</Avatar.Fallback>
        </Avatar.Root>
    );

    if (title) {
        return (
            <Tooltip.Root>
                <Tooltip.Trigger asChild>{avatar}</Tooltip.Trigger>
                <Tooltip.Content side={titleSide} align={titleAlign}>
                    {title}
                </Tooltip.Content>
            </Tooltip.Root>
        );
    }

    return avatar;
};

// ChatBubbleMessage
const chatBubbleMessageVariants = cva("relative z-10 min-w-0 max-w-full px-3.5 py-2.5 shadow-sm", {
    variants: {
        variant: {
            received: "rounded-2xl border border-border/70 bg-card/90 text-card-foreground",
            sent: "rounded-2xl bg-primary text-primary-foreground",
        },
        layout: {
            default: "",
            ai: "border-t w-full rounded-none bg-transparent",
        },
    },
    defaultVariants: {
        variant: "received",
        layout: "default",
    },
});

interface ChatBubbleMessageProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "children">, VariantProps<typeof chatBubbleMessageVariants> {
    message?: IChatContent;
    isLoading?: bool;
}

const ChatBubbleMessage = React.forwardRef<HTMLDivElement, ChatBubbleMessageProps>(
    ({ message, className, variant, layout, isLoading = false, ...props }, ref) => {
        const [t] = useTranslation();

        return (
            <div
                className={cn(chatBubbleMessageVariants({ variant, layout }), "whitespace-pre-wrap [overflow-wrap:anywhere]", className)}
                ref={ref}
                {...props}
            >
                {isLoading ? (
                    <div className="flex items-center space-x-2">
                        <MessageLoading />
                    </div>
                ) : message?.content ? (
                    <Markdown message={message} />
                ) : (
                    t("common.No message")
                )}
            </div>
        );
    }
);
ChatBubbleMessage.displayName = "ChatBubbleMessage";

interface IChatBubbleCopyButtonProps {
    message: IChatContent;
    className?: string;
}

function ChatBubbleCopyButton({ message, className }: IChatBubbleCopyButtonProps) {
    const [t] = useTranslation();
    const [isCopied, setIsCopied] = React.useState(false);
    const handleCopy = async () => {
        await copyToClipboard(message.content);
        setIsCopied(true);
        setTimeout(() => setIsCopied(false), 2000);
    };

    return (
        <Button
            variant="ghost"
            size="icon-sm"
            className={cn(className, "size-7")}
            title={t(isCopied ? "common.Copied." : "common.Copy")}
            onClick={handleCopy}
        >
            <IconComponent icon={isCopied ? "check" : "copy"} size="3.5" />
        </Button>
    );
}

// ChatBubbleTimestamp
interface ChatBubbleTimestampProps extends React.HTMLAttributes<HTMLDivElement> {
    timestamp: string;
}

const ChatBubbleTimestamp: React.FC<ChatBubbleTimestampProps> = ({ timestamp, className, ...props }) => (
    <div className={cn("mt-2 text-right text-xs", className)} {...props}>
        {timestamp}
    </div>
);

// ChatBubbleAction
type ChatBubbleActionProps = ButtonProps & {
    icon: React.ReactNode;
};

const ChatBubbleAction: React.FC<ChatBubbleActionProps> = ({ icon, onClick, className, variant = "ghost", size = "icon", ...props }) => (
    <Button variant={variant} size={size} className={className} onClick={onClick} {...props}>
        {icon}
    </Button>
);

interface ChatBubbleActionWrapperProps extends React.HTMLAttributes<HTMLDivElement> {
    variant?: "sent" | "received";
    className?: string;
}

const ChatBubbleActionWrapper = React.forwardRef<HTMLDivElement, ChatBubbleActionWrapperProps>(({ variant, className, children, ...props }, ref) => (
    <div
        ref={ref}
        className={cn(
            "absolute top-1/2 flex -translate-y-1/2 opacity-0 transition-opacity duration-200 group-hover:opacity-100",
            variant === "sent" ? "-left-1 -translate-x-full flex-row-reverse" : "-right-1 translate-x-full",
            className
        )}
        {...props}
    >
        {children}
    </div>
));
ChatBubbleActionWrapper.displayName = "ChatBubbleActionWrapper";

export {
    ChatBubble,
    ChatBubbleAvatar,
    ChatBubbleMessage,
    ChatBubbleCopyButton,
    ChatBubbleTimestamp,
    chatBubbleVariant,
    chatBubbleMessageVariants,
    ChatBubbleAction,
    ChatBubbleActionWrapper,
};
