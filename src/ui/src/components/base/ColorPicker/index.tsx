"use client";

import { forwardRef, useEffect, useMemo, useState } from "react";
import { HexColorPicker } from "react-colorful";
import { cn } from "@/core/utils/ComponentUtils";
import { useTranslation } from "react-i18next";
import Popover from "@/components/base/Popover";
import Button, { ButtonProps } from "@/components/base/Button";
import Input from "@/components/base/Input";
import Flex from "@/components/base/Flex";
import Box from "@/components/base/Box";
import SubmitButton from "@/components/base/SubmitButton";

interface ColorPickerProps {
    value: string;
    isValidating: bool;
    onSave: (value: string, endCallback: () => void) => void;
    popoverContentAlign?: "center" | "start" | "end";
    popoverContentSide?: "top" | "bottom" | "left" | "right";
    portalContainer?: HTMLElement | null;
}

const COLOR_PRESETS = [
    "#FF3B30",
    "#FF9500",
    "#FFCC00",
    "#4CD964",
    "#5AC8FA",
    "#007AFF",
    "#5856D6",
    "#FF2D55",
    "#8E8E93",
    "#EFEFF4",
    "#E5E5EA",
    "#D1D1D6",
];

const ColorPicker = forwardRef<HTMLInputElement, Omit<ButtonProps, "value" | "disabled"> & ColorPickerProps>(
    ({ isValidating, value, onSave, name, className, popoverContentAlign, popoverContentSide, portalContainer, ...props }, ref) => {
        const [open, setOpen] = useState(false);
        const [currentValue, setCurrentValue] = useState(value);
        const [t] = useTranslation();

        const parsedValue = useMemo(() => {
            return currentValue || "#FFFFFF";
        }, [currentValue]);

        useEffect(() => {
            setCurrentValue(value);
        }, [value]);

        const changeOpenState = (state: bool) => {
            if (!state) {
                setCurrentValue(value);
            }
            setOpen(state);
        };

        const save = () => {
            onSave(currentValue, () => {
                changeOpenState(false);
            });
        };

        return (
            <Popover.Root onOpenChange={changeOpenState} open={open}>
                <Popover.Trigger asChild disabled={isValidating}>
                    <Button
                        {...props}
                        className={cn("block", className)}
                        name={name}
                        onClick={() => changeOpenState(true)}
                        size="icon"
                        style={{
                            backgroundColor: value || "#FFFFFF",
                        }}
                        variant="outline"
                    >
                        <div />
                    </Button>
                </Popover.Trigger>
                <Popover.Content
                    portalContainer={portalContainer}
                    className="z-[60] w-full max-w-60 sm:max-w-96"
                    align={popoverContentAlign}
                    side={popoverContentSide}
                >
                    <Flex direction={{ initial: "col", sm: "row" }} gap="2" justify="center">
                        <Box w={{ initial: "full", sm: "52" }}>
                            <HexColorPicker color={parsedValue} onChange={setCurrentValue} className="!h-44 !w-full" />
                            <Input
                                maxLength={7}
                                onChange={(e) => {
                                    setCurrentValue(e?.currentTarget?.value);
                                }}
                                h="sm"
                                className="mt-3"
                                value={parsedValue}
                                ref={ref}
                            />
                        </Box>
                        <Flex gap={{ initial: "1.5", sm: "2" }} wrap justify="center" maxW={{ sm: "16" }}>
                            {COLOR_PRESETS.map((color) => (
                                <Button
                                    key={color}
                                    onClick={() => {
                                        setCurrentValue(color);
                                    }}
                                    style={{
                                        backgroundColor: color,
                                    }}
                                    variant="outline"
                                    className="size-7 p-0 transition-all hover:scale-125"
                                >
                                    <span />
                                </Button>
                            ))}
                        </Flex>
                    </Flex>
                    <Flex items="center" justify="end" gap="1" mt="3">
                        <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => changeOpenState(false)}>
                            {t("common.Cancel")}
                        </Button>
                        <SubmitButton type="button" size="sm" onClick={save} isValidating={isValidating}>
                            {t("common.Save")}
                        </SubmitButton>
                    </Flex>
                </Popover.Content>
            </Popover.Root>
        );
    }
);
ColorPicker.displayName = "ColorPicker";

export default ColorPicker;
