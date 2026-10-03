import { useLayoutEffect, useRef } from "react";
import Button, { ButtonProps } from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent, { TIconName } from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";

export interface IFloatingNavItem {
    key?: React.Key;
    label: React.ReactNode;
    icon: TIconName;
    badge?: React.ReactNode;
    active?: bool;
    hidden?: bool;
    disabled?: bool;
    variant?: ButtonProps["variant"];
    onClick?: () => void;
    className?: string;
    labelClassName?: string;
}

export interface IFloatingNavProps {
    items: IFloatingNavItem[];
    fixed?: bool;
    className?: string;
    contentClassName?: string;
    itemClassName?: string;
    labelClassName?: string;
    iconSize?: React.ComponentProps<typeof IconComponent>["size"];
    trailing?: React.ReactNode;
}

function Nav({
    items,
    fixed = false,
    className,
    contentClassName,
    itemClassName,
    labelClassName,
    iconSize = "4",
    trailing,
}: IFloatingNavProps): React.JSX.Element | null {
    const host = useRef<HTMLDivElement>(null);
    useLayoutEffect(() => {
        if (!fixed || !host.current) return;
        const main = document.querySelector("main");
        const board = document.getElementById("board-scrollport");
        const update = () =>
            host.current?.style.setProperty(
                "--floating-left",
                `${Math.max(main?.getBoundingClientRect().left ?? 0, board?.getBoundingClientRect().left ?? 0) + 8}px`
            );
        const observer = new ResizeObserver(update);
        if (main) observer.observe(main);
        if (board) observer.observe(board);
        window.addEventListener("resize", update);
        update();
        return () => {
            observer.disconnect();
            window.removeEventListener("resize", update);
        };
    }, [fixed]);
    const visibleItems = items.filter((item) => !item.hidden);

    if (visibleItems.length === 0 && !trailing) {
        return null;
    }

    return (
        <Flex
            ref={host}
            justify="center"
            className={cn(
                "pointer-events-none z-50 w-full shrink-0",
                fixed && "fixed bottom-2 left-[var(--floating-left,8px)] right-2 w-auto",
                className
            )}
        >
            <Flex
                data-floating-nav-content=""
                items="center"
                gap="1"
                className={cn(
                    "pointer-events-auto w-full max-w-full rounded-2xl border bg-background/95 p-1 shadow-lg backdrop-blur md:w-auto md:rounded-full",
                    contentClassName
                )}
            >
                {visibleItems.map((item, index) => (
                    <Button
                        key={item.key ?? index}
                        type="button"
                        variant={item.variant ?? (item.active ? "default" : "ghost")}
                        disabled={item.disabled}
                        className={cn(
                            "relative h-11 min-w-0 flex-1 gap-1 rounded-xl px-2 md:flex-none md:rounded-full md:px-4",
                            itemClassName,
                            item.className
                        )}
                        onClick={item.onClick}
                        aria-label={typeof item.label === "string" ? item.label : undefined}
                    >
                        {item.badge && (
                            <span
                                className={cn(
                                    "absolute -right-1 -top-1 inline-flex min-w-5 items-center justify-center rounded-full bg-destructive",
                                    "px-1.5 py-0.5 text-[10px] font-bold leading-none text-destructive-foreground shadow"
                                )}
                            >
                                {item.badge}
                            </span>
                        )}
                        <IconComponent icon={item.icon} size={iconSize} />
                        <span className={cn("truncate text-xs", labelClassName, item.labelClassName)}>{item.label}</span>
                    </Button>
                ))}
                {trailing}
            </Flex>
        </Flex>
    );
}

export default Nav;
