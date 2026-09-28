/* eslint-disable @/max-len */
"use client";

import type { DialogProps } from "@radix-ui/react-dialog";
import { Command as Primitive } from "cmdk";
import * as React from "react";
import BaseDialog from "@/components/base/Dialog";
import IconComponent from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";
import { tv } from "tailwind-variants";

const Root = React.forwardRef<React.ComponentRef<typeof Primitive>, React.ComponentPropsWithoutRef<typeof Primitive>>(
    ({ className, ...props }, ref) => (
        <Primitive
            ref={ref}
            className={cn("flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground", className)}
            {...props}
        />
    )
);
Root.displayName = Primitive.displayName;

export interface CommandDialogProps extends DialogProps {}

const Dialog = ({ children, ...props }: CommandDialogProps) => {
    return (
        <BaseDialog.Root {...props}>
            <BaseDialog.Content className="w-[calc(100vw-1rem)] max-w-lg overflow-hidden p-0 shadow-lg sm:w-full">
                <Root className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group]:not([hidden])_~[cmdk-group]]:pt-0 [&_[cmdk-group]]:px-2 [&_[cmdk-input-wrapper]_svg]:h-5 [&_[cmdk-input-wrapper]_svg]:w-5 [&_[cmdk-input]]:h-12 [&_[cmdk-item]]:px-2 [&_[cmdk-item]]:py-3 [&_[cmdk-item]_svg]:h-5 [&_[cmdk-item]_svg]:w-5">
                    {children}
                </Root>
            </BaseDialog.Content>
        </BaseDialog.Root>
    );
};

const Input = React.forwardRef<
    React.ComponentRef<typeof Primitive.Input>,
    React.ComponentPropsWithoutRef<typeof Primitive.Input> & {
        withoutIcon?: bool;
    }
>(({ className, withoutIcon = false, ...props }, ref) => (
    <div className="flex items-center border-b px-3" cmdk-input-wrapper="">
        {!withoutIcon && <IconComponent icon="search" size="4" className="mr-2 shrink-0 opacity-50" />}
        <Primitive.Input
            ref={ref}
            className={cn(
                "flex h-11 w-full rounded-md bg-transparent py-3 text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
                className
            )}
            {...props}
        />
    </div>
));

Input.displayName = Primitive.Input.displayName;

const List = React.forwardRef<React.ComponentRef<typeof Primitive.List>, React.ComponentPropsWithoutRef<typeof Primitive.List>>(
    ({ className, ...props }, ref) => (
        <Primitive.List ref={ref} className={cn("max-h-[min(70vh,300px)] overflow-y-auto overflow-x-hidden", className)} {...props} />
    )
);

List.displayName = Primitive.List.displayName;

const Empty = React.forwardRef<React.ComponentRef<typeof Primitive.Empty>, React.ComponentPropsWithoutRef<typeof Primitive.Empty>>((props, ref) => (
    <Primitive.Empty ref={ref} className="py-6 text-center text-sm" {...props} />
));

Empty.displayName = Primitive.Empty.displayName;

const GroupVariants = tv({
    base: "overflow-hidden p-1 text-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground",
});

const Group = React.forwardRef<React.ComponentRef<typeof Primitive.Group>, React.ComponentPropsWithoutRef<typeof Primitive.Group>>(
    ({ className, ...props }, ref) => <Primitive.Group ref={ref} className={cn(GroupVariants(), className)} {...props} />
);

Group.displayName = Primitive.Group.displayName;

const Separator = React.forwardRef<React.ComponentRef<typeof Primitive.Separator>, React.ComponentPropsWithoutRef<typeof Primitive.Separator>>(
    ({ className, ...props }, ref) => <Primitive.Separator ref={ref} className={cn("-mx-1 h-px bg-border", className)} {...props} />
);
Separator.displayName = Primitive.Separator.displayName;

const ItemVariants = tv({
    base: "relative flex cursor-default select-none items-center rounded-sm px-2 py-1.5 text-sm outline-none data-[disabled=true]:pointer-events-none data-[selected='true']:bg-accent data-[selected=true]:text-accent-foreground data-[disabled=true]:opacity-50",
});

const Item = React.forwardRef<React.ComponentRef<typeof Primitive.Item>, React.ComponentPropsWithoutRef<typeof Primitive.Item>>(
    ({ className, ...props }, ref) => <Primitive.Item ref={ref} className={cn(ItemVariants(), className)} {...props} />
);

Item.displayName = Primitive.Item.displayName;

const Shortcut = ({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) => {
    return <span className={cn("ml-auto text-xs tracking-widest text-muted-foreground", className)} {...props} />;
};
Shortcut.displayName = "CommandShortcut";

type TCommandModule = {
    Dialog: (props: CommandDialogProps) => React.JSX.Element;
    Empty: typeof Empty;
    GroupVariants: typeof GroupVariants;
    Group: typeof Group;
    Input: typeof Input;
    ItemVariants: typeof ItemVariants;
    Item: typeof Item;
    List: typeof List;
    Primitive: typeof Primitive;
    Root: typeof Root;
    Separator: typeof Separator;
    Shortcut: typeof Shortcut;
};

export default {
    Dialog,
    Empty,
    GroupVariants,
    Group,
    Input,
    ItemVariants,
    Item,
    List,
    Primitive,
    Root,
    Separator,
    Shortcut,
} as TCommandModule;
