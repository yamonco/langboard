import { useTranslation } from "react-i18next";
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { ChevronRight, MoreHorizontal } from "lucide-react";
import { cn } from "@/core/utils/ComponentUtils";

const Root = React.forwardRef<
    HTMLElement,
    React.ComponentPropsWithoutRef<"nav"> & {
        separator?: React.ReactNode;
    }
>(({ ...props }, ref) => {
    const [t] = useTranslation();
    return <nav ref={ref} aria-label={t("common.Breadcrumb")} {...props} />;
});
Root.displayName = "Breadcrumb";

const List = React.forwardRef<HTMLOListElement, React.ComponentPropsWithoutRef<"ol">>(({ className, ...props }, ref) => (
    <ol ref={ref} className={cn("flex flex-wrap items-center gap-1.5 break-words text-sm text-muted-foreground sm:gap-2.5", className)} {...props} />
));
List.displayName = "BreadcrumbList";

const Item = React.forwardRef<HTMLLIElement, React.ComponentPropsWithoutRef<"li">>(({ className, ...props }, ref) => (
    <li ref={ref} className={cn("inline-flex items-center gap-1.5", className)} {...props} />
));
Item.displayName = "BreadcrumbItem";

const Link = React.forwardRef<
    HTMLAnchorElement,
    React.ComponentPropsWithoutRef<"a"> & {
        asChild?: bool;
    }
>(({ asChild, className, ...props }, ref) => {
    const Comp = asChild ? Slot : "a";

    return <Comp ref={ref} className={cn("transition-colors hover:text-foreground", className)} {...props} />;
});
Link.displayName = "BreadcrumbLink";

const Page = React.forwardRef<HTMLSpanElement, React.ComponentPropsWithoutRef<"span">>(({ className, ...props }, ref) => (
    <span ref={ref} role="link" aria-disabled="true" aria-current="page" className={cn("font-normal text-foreground", className)} {...props} />
));
Page.displayName = "BreadcrumbPage";

function Separator({ children, className, ...props }: React.ComponentProps<"li">) {
    return (
        <li role="presentation" aria-hidden="true" className={cn("[&>svg]:size-3.5", className)} {...props}>
            {children ?? <ChevronRight />}
        </li>
    );
}
Separator.displayName = "BreadcrumbSeparator";

function Ellipsis({ className, ...props }: React.ComponentProps<"span">) {
    const [t] = useTranslation();
    return (
        <span role="presentation" aria-hidden="true" className={cn("flex size-9 items-center justify-center", className)} {...props}>
            <MoreHorizontal className="size-4" />
            <span className="sr-only">{t("common.More")}</span>
        </span>
    );
}
Ellipsis.displayName = "BreadcrumbEllipsis";

export default {
    Root,
    List,
    Item,
    Link,
    Page,
    Separator,
    Ellipsis,
};
