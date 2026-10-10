import { forwardRef, memo } from "react";
import { ISidebarNavItem, TSidebarNavItemsProps } from "@/components/Sidebar/types";
import { ButtonVariants } from "@/components/base/Button";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Tooltip from "@/components/base/Tooltip";
import { cn } from "@/core/utils/ComponentUtils";

const SidebarNavItems = memo(({ isFloating, isCollapsed, navs }: TSidebarNavItemsProps): React.JSX.Element => {
    return (
        <>
            {navs.map((item, index) => {
                const key = getSidebarNavItemKey(item, index);
                const Comp = isFloating ? FloatingNavItem : SidebarNavItem;

                return (
                    <Tooltip.Root key={`${key}:${Boolean(isFloating || isCollapsed)}`} open={isFloating || isCollapsed ? undefined : false}>
                        <Tooltip.Trigger asChild>
                            <span className="w-full">
                                <Comp item={item} />
                            </span>
                        </Tooltip.Trigger>
                        {(isFloating || isCollapsed) && (
                            <Tooltip.Portal>
                                <Tooltip.Content side="right">{item.name}</Tooltip.Content>
                            </Tooltip.Portal>
                        )}
                    </Tooltip.Root>
                );
            })}
        </>
    );
});

function getSidebarNavItemKey(item: ISidebarNavItem, index: number): string {
    return item.href || `${item.name}-${index}`;
}

interface ISidebarNavItemProps {
    item: ISidebarNavItem;
}

const FloatingNavItem = forwardRef<HTMLAnchorElement, ISidebarNavItemProps>(({ item, ...props }, ref): React.JSX.Element => {
    return (
        <Floating.Button.Item>
            <a
                href={item.href}
                onClick={item.onClick}
                aria-label={item.name}
                aria-current={item.current ? "page" : undefined}
                className={ButtonVariants({
                    variant: "secondary",
                    size: "icon",
                    className: cn(
                        item.current ? "bg-muted text-primary" : "",
                        "size-14 cursor-pointer rounded-full opacity-70",
                        item.hidden && "hidden"
                    ),
                })}
                ref={ref}
                {...props}
            >
                <IconComponent icon={item.icon} size="6" strokeWidth="2" />
            </a>
        </Floating.Button.Item>
    );
});

const SidebarNavItem = forwardRef<HTMLAnchorElement, ISidebarNavItemProps>(({ item, ...props }, ref): React.JSX.Element => {
    return (
        <a
            {...props}
            href={item.href}
            onClick={item.onClick}
            aria-label={item.name}
            aria-current={item.current ? "page" : undefined}
            className={cn(
                item.current ? "text-primary group-data-[collapsed=false]/sidebar:bg-muted" : "text-muted-foreground",
                "select-none group-data-[fullscreen=false]/floating:justify-center",
                "inline-flex w-full cursor-pointer items-center gap-3 rounded-lg py-1 text-base",
                "transition-all duration-100 hover:text-primary",
                "group-data-[collapsed=false]/sidebar:px-3 group-data-[collapsed=false]/sidebar:py-2",
                item.hidden && "hidden"
            )}
            ref={ref}
        >
            <IconComponent
                icon={item.icon}
                className={cn(
                    "max-h-5 min-h-5 min-w-5 max-w-5",
                    "group-data-[collapsed=true]/sidebar:min-h-8 group-data-[collapsed=true]/sidebar:min-w-8",
                    "group-data-[collapsed=true]/sidebar:max-h-8 group-data-[collapsed=true]/sidebar:max-w-8",
                    "group-data-[fullscreen=false]/floating:min-h-8 group-data-[fullscreen=false]/floating:min-w-8",
                    "group-data-[fullscreen=false]/floating:max-h-8 group-data-[fullscreen=false]/floating:max-w-8",
                    "stroke-2 transition-all duration-100 group-data-[collapsed=true]/sidebar:stroke-1"
                )}
            />
            <span className="hidden truncate transition-all duration-100 group-data-[collapsed=false]/sidebar:block">{item.name}</span>
        </a>
    );
});

export default SidebarNavItems;
