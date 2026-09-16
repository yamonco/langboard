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
    const visibleItems = items.filter((item) => !item.hidden);

    if (visibleItems.length === 0) {
        return null;
    }

    return (
        <Flex
            justify="center"
            className={cn(
                "pointer-events-none z-50 w-full shrink-0",
                fixed && "fixed bottom-2 left-2 right-2 w-auto md:left-1/2 md:right-auto md:-translate-x-1/2",
                className
            )}
        >
            <Flex
                items="center"
                gap="1"
                className={cn(
                    "pointer-events-auto w-full rounded-2xl border bg-background/95 p-1 shadow-lg backdrop-blur md:w-auto md:rounded-full",
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
