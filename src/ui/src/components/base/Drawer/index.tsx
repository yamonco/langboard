"use client";

import * as React from "react";
import { Drawer as DrawerPrimitive } from "vaul";
import { cn } from "@/core/utils/ComponentUtils";
import { FocusScope } from "@radix-ui/react-focus-scope";
import { DialogContentProps } from "@radix-ui/react-dialog";

const Root = ({ shouldScaleBackground = true, ...props }: React.ComponentProps<typeof DrawerPrimitive.Root>) => (
    <DrawerPrimitive.Root shouldScaleBackground={shouldScaleBackground} {...props} />
);
Root.displayName = "Drawer";

const Trigger: typeof DrawerPrimitive.Trigger = DrawerPrimitive.Trigger;

const Portal = DrawerPrimitive.Portal;

const Close: typeof DrawerPrimitive.Close = DrawerPrimitive.Close;

const Handle = DrawerPrimitive.Handle;

const Overlay: typeof DrawerPrimitive.Overlay = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Overlay>,
    React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Overlay>
>(({ className, ...props }, ref) => <DrawerPrimitive.Overlay ref={ref} className={cn("fixed inset-0 z-50 bg-black/80", className)} {...props} />);
Overlay.displayName = DrawerPrimitive.Overlay.displayName;

type TContent = React.ForwardRefExoticComponent<
    Omit<Omit<DialogContentProps & React.RefAttributes<HTMLDivElement>, "ref"> & React.RefAttributes<HTMLDivElement>, "ref"> & {
        withGrabber?: bool;
        focusGuards?: bool;
        overlayClassName?: string;
    } & React.RefAttributes<HTMLDivElement>
>;

const Content: TContent = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Content>,
    React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Content> & { withGrabber?: bool; focusGuards?: bool; overlayClassName?: string }
>(({ className, children, withGrabber = true, focusGuards = true, overlayClassName, ...props }, ref) => {
    let content = (
        <DrawerPrimitive.Content
            ref={ref}
            className={cn(
                "fixed inset-x-0 bottom-0 z-50 mt-24 flex h-auto flex-col rounded-t-[10px] border bg-background focus-visible:outline-none",
                className
            )}
            {...props}
        >
            {withGrabber && <div className="mx-auto mt-4 h-2 w-[100px] rounded-full bg-muted" />}
            {children}
        </DrawerPrimitive.Content>
    );

    if (!focusGuards) {
        content = (
            <FocusScope trapped={false} loop={false}>
                {content}
            </FocusScope>
        );
    }

    return (
        <Portal>
            <Overlay className={overlayClassName} />
            {content}
        </Portal>
    );
});
Content.displayName = "DrawerContent";

const Header = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div className={cn("grid gap-1.5 p-4 text-center sm:text-left", className)} {...props} />
);
Header.displayName = "DrawerHeader";

const Footer = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
    <div className={cn("mt-auto flex flex-col gap-2 p-4", className)} {...props} />
);
Footer.displayName = "DrawerFooter";

const Title: typeof DrawerPrimitive.Title = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Title>,
    React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Title>
>(({ className, ...props }, ref) => (
    <DrawerPrimitive.Title ref={ref} className={cn("text-lg font-semibold leading-none tracking-tight", className)} {...props} />
));
Title.displayName = DrawerPrimitive.Title.displayName;

const Description: typeof DrawerPrimitive.Description = React.forwardRef<
    React.ComponentRef<typeof DrawerPrimitive.Description>,
    React.ComponentPropsWithoutRef<typeof DrawerPrimitive.Description>
>(({ className, ...props }, ref) => <DrawerPrimitive.Description ref={ref} className={cn("text-sm text-muted-foreground", className)} {...props} />);
Description.displayName = DrawerPrimitive.Description.displayName;

export default {
    Close,
    Handle,
    Content,
    Description,
    Footer,
    Header,
    Overlay,
    Portal,
    Root,
    Title,
    Trigger,
};
