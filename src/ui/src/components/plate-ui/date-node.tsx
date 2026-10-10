"use client";

import { normalizeLocale } from "@/core/utils/LocalePolicy";

import type { TDateElement } from "platejs";
import type { PlateElementProps } from "platejs/react";
import { PlateElement, useReadOnly } from "platejs/react";
import Calendar from "@/components/base/Calendar";
import Popover from "@/components/base/Popover";
import { useTranslation } from "react-i18next";
import { cn } from "@/core/utils/ComponentUtils";

export function DateElement(props: PlateElementProps<TDateElement>) {
    const [t, i18n] = useTranslation();
    const { editor, element } = props;

    const readOnly = useReadOnly();

    const trigger = (
        <span className={cn("w-fit cursor-pointer rounded-sm bg-muted px-1 text-muted-foreground")} contentEditable={false} draggable>
            {element.date ? (
                (() => {
                    const today = new Date();
                    const elementDate = new Date(element.date);
                    const isToday =
                        elementDate.getDate() === today.getDate() &&
                        elementDate.getMonth() === today.getMonth() &&
                        elementDate.getFullYear() === today.getFullYear();

                    const isYesterday = new Date(today.setDate(today.getDate() - 1)).toDateString() === elementDate.toDateString();
                    const isTomorrow = new Date(today.setDate(today.getDate() + 2)).toDateString() === elementDate.toDateString();

                    if (isToday) return t("editor.Today");
                    if (isYesterday) return t("editor.Yesterday");
                    if (isTomorrow) return t("editor.Tomorrow");

                    return elementDate.toLocaleDateString(normalizeLocale(i18n.language), {
                        day: "numeric",
                        month: "long",
                        year: "numeric",
                    });
                })()
            ) : (
                <span>{t("editor.Pick a date")}</span>
            )}
        </span>
    );

    if (readOnly) {
        return trigger;
    }

    return (
        <PlateElement
            {...props}
            className="inline-block"
            attributes={{
                ...props.attributes,
                contentEditable: false,
            }}
        >
            <Popover.Root>
                <Popover.Trigger asChild>{trigger}</Popover.Trigger>
                <Popover.Content className="w-auto p-0">
                    <Calendar
                        value={new Date(element.date as string)}
                        onChange={(date) => {
                            if (!date) return;

                            editor.tf.setNodes({ date: date.toDateString() }, { at: element });
                        }}
                        hideTime
                        autoFocus
                    />
                </Popover.Content>
            </Popover.Root>
            {props.children}
        </PlateElement>
    );
}
