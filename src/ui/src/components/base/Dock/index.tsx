/* eslint-disable @typescript-eslint/no-explicit-any */
"use client";

import { motion, useMotionValue, useSpring, useTransform, type MotionValue } from "framer-motion";
import type { PropsWithChildren } from "react";
import React, { useRef } from "react";
import { VariantProps, tv } from "tailwind-variants";
import Tooltip from "@/components/base/Tooltip";
import { ButtonProps } from "@/components/base/Button";
import IconComponent from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";

export interface DockProps extends VariantProps<typeof DockVariants> {
    className?: string;
    magnification?: number;
    distance?: number;
    direction?: "top" | "middle" | "bottom";
    children: React.ReactNode;
}

const DEFAULT_MAGNIFICATION = 60;
const DEFAULT_DISTANCE = 140;
const MouseXContext = React.createContext<MotionValue<number> | null>(null);

const DockVariants = tv(
    {
        // eslint-disable-next-line @/max-len
        base: "supports-backdrop-blur:bg-white/10 supports-backdrop-blur:dark:bg-black/10 mx-auto mt-2 md:mt-4 flex w-max gap-2 rounded-2xl border p-2 backdrop-blur-md",
        variants: {
            size: {
                xs: "h-8",
                sm: "h-12",
                md: "h-14",
                lg: "h-16",
                xl: "h-20",
            },
        },
        defaultVariants: {
            size: "md",
        },
    },
    {
        responsiveVariants: true,
    }
);

const Root = React.forwardRef<HTMLDivElement, DockProps>(
    ({ className, children, size, magnification = DEFAULT_MAGNIFICATION, distance = DEFAULT_DISTANCE, direction = "bottom", ...props }, ref) => {
        const mouseX = useMotionValue(Infinity);

        const renderChildren = () => {
            return React.Children.map(children, (child) => {
                if (React.isValidElement(child) && (child.type === Icon || child.type === Button)) {
                    if (child.type === Button) {
                        return React.cloneElement(child, {
                            ...(child.props as any),
                            dockIconProps: {
                                ...(child.props as any).dockIconProps,
                                mouseX,
                                magnification,
                                distance,
                            },
                        } as any);
                    }

                    return React.cloneElement(child, {
                        ...(child.props as any),
                        mouseX,
                        magnification,
                        distance,
                    });
                }
                return child;
            });
        };

        return (
            <MouseXContext.Provider value={mouseX}>
                <motion.div
                    ref={ref}
                    onMouseMove={(e) => mouseX.set(e.pageX)}
                    onMouseLeave={() => mouseX.set(Infinity)}
                    {...props}
                    className={cn(
                        DockVariants({ size }),
                        direction === "top" ? "items-start" : "",
                        direction === "middle" ? "items-center" : "",
                        direction === "bottom" ? "items-end" : "",
                        className
                    )}
                >
                    {renderChildren()}
                </motion.div>
            </MouseXContext.Provider>
        );
    }
);

Root.displayName = "Dock";

export interface DockIconProps {
    magnification?: number;
    distance?: number;

    mouseX?: any;
    className?: string;
    children?: React.ReactNode;
    props?: PropsWithChildren;
}

function Icon({ magnification = DEFAULT_MAGNIFICATION, distance = DEFAULT_DISTANCE, mouseX, className, children, ...props }: DockIconProps) {
    const ref = useRef<HTMLDivElement>(null);
    const contextMouseX = React.useContext(MouseXContext);
    const fallbackMouseX = useMotionValue(Infinity);

    const distanceCalc = useTransform(mouseX ?? contextMouseX ?? fallbackMouseX, (val: number) => {
        const bounds = ref.current?.getBoundingClientRect() ?? { x: 0, width: 0 };

        return val - bounds.x - bounds.width / 2;
    });

    const widthSync = useTransform(distanceCalc, [-distance, 0, distance], [40, magnification, 40]);

    const width = useSpring(widthSync, {
        mass: 0.1,
        stiffness: 150,
        damping: 12,
    });

    return (
        <motion.div
            ref={ref}
            style={{ width }}
            className={cn("flex aspect-square cursor-pointer items-center justify-center rounded-full", className)}
            {...props}
        >
            {children}
        </motion.div>
    );
}

Icon.displayName = "DockIcon";

interface IBaseDockButtonProps extends Pick<ButtonProps, "title" | "titleSide"> {
    buttonProps: Omit<ButtonProps, "children" | "title" | "titleSide">;
    dockIconProps: Omit<DockIconProps, "children" | "props">;
    icon?: string;
    children?: React.ReactNode;
}

interface IDockIconButtonProps extends IBaseDockButtonProps {
    icon: string;
}

interface IDockCustomButtonProps extends IBaseDockButtonProps {
    children: React.ReactNode;
}

export type TDockButtonProps = IDockIconButtonProps | IDockCustomButtonProps;

function Button({ buttonProps, dockIconProps, title, titleSide, icon, children }: TDockButtonProps) {
    let iconComp;
    if (icon) {
        iconComp = <IconComponent icon={icon} className="size-full" />;
    } else {
        iconComp = children;
    }

    if (title) {
        iconComp = (
            <Tooltip.Root disableHoverableContent>
                <Tooltip.Trigger {...buttonProps}>{iconComp}</Tooltip.Trigger>
                <Tooltip.Content side={titleSide}>{title}</Tooltip.Content>
            </Tooltip.Root>
        );
    } else {
        iconComp = <button {...buttonProps}>{iconComp}</button>;
    }
    return <Icon {...dockIconProps}>{iconComp}</Icon>;
}

export default {
    DockVariants,
    Icon,
    Button,
    Root,
};
