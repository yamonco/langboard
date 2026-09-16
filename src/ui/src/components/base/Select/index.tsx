/* eslint-disable @/max-len */
"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import * as React from "react";
import { cn } from "@/core/utils/ComponentUtils";
import IconComponent from "@/components/base/IconComponent";

const Root = SelectPrimitive.Root;

const Group = SelectPrimitive.Group;

const Value = SelectPrimitive.Value;

const Trigger = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>>(
    ({ className, children, ...props }, ref) => (
        <SelectPrimitive.Trigger
            ref={ref}
            className={cn(
                "flex h-10 w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
                "[&[data-state=open]>svg.lucide-chevron-down]:rotate-180",
                className
            )}
            {...props}
        >
            {children}
            <SelectPrimitive.Icon asChild>
                <IconComponent icon="chevron-down" size="4" className="opacity-50 transition-all" />
            </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
    )
);
Trigger.displayName = SelectPrimitive.Trigger.displayName;

const ScrollUpButton = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.ScrollUpButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollUpButton ref={ref} className={cn("flex cursor-default items-center justify-center py-1", className)} {...props}>
        <IconComponent icon="chevron-up" size="4" />
    </SelectPrimitive.ScrollUpButton>
));
ScrollUpButton.displayName = SelectPrimitive.ScrollUpButton.displayName;

const ScrollDownButton = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.ScrollDownButton>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownButton>
>(({ className, ...props }, ref) => (
    <SelectPrimitive.ScrollDownButton ref={ref} className={cn("flex cursor-default items-center justify-center py-1", className)} {...props}>
        <IconComponent icon="chevron-down" size="4" />
    </SelectPrimitive.ScrollDownButton>
));
ScrollDownButton.displayName = SelectPrimitive.ScrollDownButton.displayName;

export interface ISelectContentProps extends React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content> {
    container?: React.ComponentPropsWithoutRef<typeof SelectPrimitive.Portal>["container"];
}

const Content = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Content>, ISelectContentProps>(
    ({ className, children, container, position = "popper", ...props }, ref) => (
        <SelectPrimitive.Portal container={container}>
            <SelectPrimitive.Content
                ref={ref}
                className={cn(
                    "relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
                    position === "popper" &&
                        "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
                    className
                )}
                position={position}
                {...props}
            >
                <ScrollUpButton />
                <SelectPrimitive.Viewport
                    className={cn(
                        "p-1",
                        position === "popper" && "h-[var(--radix-select-trigger-height)] w-full min-w-[var(--radix-select-trigger-width)]"
                    )}
                >
                    {children}
                </SelectPrimitive.Viewport>
                <ScrollDownButton />
            </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
    )
);
Content.displayName = SelectPrimitive.Content.displayName;

const Label = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Label>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Label>>(
    ({ className, ...props }, ref) => (
        <SelectPrimitive.Label ref={ref} className={cn("py-1.5 pl-8 pr-2 text-sm font-semibold", className)} {...props} />
    )
);
Label.displayName = SelectPrimitive.Label.displayName;

const Item = React.forwardRef<React.ComponentRef<typeof SelectPrimitive.Item>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>>(
    ({ className, children, ...props }, ref) => (
        <SelectPrimitive.Item
            ref={ref}
            className={cn(
                "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
                className
            )}
            {...props}
        >
            <span className="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <SelectPrimitive.ItemIndicator>
                    <IconComponent icon="check" size="4" />
                </SelectPrimitive.ItemIndicator>
            </span>

            <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
        </SelectPrimitive.Item>
    )
);
Item.displayName = SelectPrimitive.Item.displayName;

const Separator = React.forwardRef<
    React.ComponentRef<typeof SelectPrimitive.Separator>,
    React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => <SelectPrimitive.Separator ref={ref} className={cn("-mx-1 my-1 h-px bg-muted", className)} {...props} />);
Separator.displayName = SelectPrimitive.Separator.displayName;

export default {
    Content,
    Group,
    Item,
    Label,
    Root,
    ScrollDownButton,
    ScrollUpButton,
    Separator,
    Trigger,
    Value,
};
