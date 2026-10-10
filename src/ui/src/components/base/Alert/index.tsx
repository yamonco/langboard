/* eslint-disable @/max-len */
"use client";

import { useTranslation } from "react-i18next";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/core/utils/ComponentUtils";
import IconComponent from "@/components/base/IconComponent";

export const AlertVariants = cva("relative w-full rounded-lg border p-4 text-sm transition-colors", {
    variants: {
        variant: {
            default: "border-[hsl(var(--hu-border))] bg-[hsl(var(--hu-card))] text-[hsl(var(--hu-card-foreground))]",
            destructive:
                "border-[hsl(var(--hu-destructive))] bg-[hsl(var(--hu-destructive))]/10 text-[hsl(var(--hu-destructive))] [&>svg]:text-[hsl(var(--hu-destructive))]",
            warning: "border-warning-border bg-warning text-warning-foreground dark:bg-warning/30 [&>svg]:text-amber-600 dark:[&>svg]:text-amber-400",
            success:
                "border-green-200 bg-green-50 text-green-800 dark:border-green-700 dark:bg-green-950/30 dark:text-green-200 [&>svg]:text-green-600 dark:[&>svg]:text-green-400",
            info: "border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-700 dark:bg-blue-950/30 dark:text-blue-200 [&>svg]:text-blue-600 dark:[&>svg]:text-blue-400",
        },
    },
    defaultVariants: {
        variant: "default",
    },
});

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof AlertVariants> {
    icon?: React.ComponentProps<typeof IconComponent>["icon"];
    title?: string;
    dismissible?: bool;
    onDismiss?: () => void;
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(({ className, variant, icon, title, dismissible, onDismiss, children, ...props }, ref) => {
    const [t] = useTranslation();
    const [isVisible, setIsVisible] = React.useState(true);

    const handleDismiss = () => {
        setIsVisible(false);
        setTimeout(() => {
            onDismiss?.();
        }, 150); // Match the exit animation duration
    };

    // Extract motion-conflicting props
    const { onDrag, onDragStart, onDragEnd, onAnimationStart, onAnimationEnd, onAnimationIteration, onTransitionEnd, ...motionProps } = props;

    return (
        <AnimatePresence>
            {isVisible && (
                <motion.div
                    ref={ref}
                    className={cn(AlertVariants({ variant }), className)}
                    initial={{ opacity: 0, y: -10, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -10, scale: 0.95 }}
                    transition={{ duration: 0.15, ease: "easeOut" }}
                    role="alert"
                    {...motionProps}
                >
                    <div className="flex">
                        {!!icon && (
                            <div className="flex-shrink-0">
                                <IconComponent icon={icon} size="4" className="mt-0.5" />
                            </div>
                        )}
                        <div className={cn("flex-1", !!icon && "ml-3")}>
                            {title && <h3 className="mb-1 text-sm font-medium">{title}</h3>}
                            <div className={cn("text-sm", title && "text-muted-foreground")}>{children}</div>
                        </div>
                        {dismissible && (
                            <div className="ml-3 flex-shrink-0">
                                <button
                                    type="button"
                                    className="inline-flex rounded-md p-1.5 transition-colors hover:bg-black/5 focus:outline-none focus:ring-2 focus:ring-[hsl(var(--hu-ring))] focus:ring-offset-2 dark:hover:bg-white/5"
                                    onClick={handleDismiss}
                                    aria-label={t("common.Dismiss alert")}
                                >
                                    <IconComponent icon="x" size="4" />
                                </button>
                            </div>
                        )}
                    </div>
                </motion.div>
            )}
        </AnimatePresence>
    );
});
Alert.displayName = "Alert";

export default Alert;
