import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Tooltip from "@/components/base/Tooltip";
import { IModelMap, TPickedModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { memo, useState } from "react";
import Popover from "@/components/base/Popover";
import { cn } from "@/core/utils/ComponentUtils";
import { ProjectLabel } from "@/core/models";
import { useTranslation } from "react-i18next";
import { globalLabelDisplay } from "@/core/utils/LabelDisplay";

interface ILabelModel {
    name: string;
    color: string;
    description?: string;
}

export type TLabelModelName = {
    [TKey in keyof IModelMap]: TPickedModel<TKey> extends ILabelModel ? TKey : never;
}[keyof IModelMap];
export type TLabelModel<TModelName extends TLabelModelName> = TPickedModel<TModelName>;

export interface ILabelBadgeProps extends ILabelModel {
    textColor?: string;
    noTooltip?: bool;
    compact?: boolean;
    emoji?: string;
}

export const LabelBadge = memo(({ name, color, textColor, description, noTooltip, compact, emoji }: ILabelBadgeProps) => {
    const [expanded, setExpanded] = useState(false);
    const currentColor = color || "#FFFFFF";
    const currentDescription = description || name;

    const badge = (
        <Box className="select-none" position="relative">
            <Box
                className="opacity-50"
                rounded="xl"
                size="full"
                position="absolute"
                top="0"
                left="0"
                style={{
                    backgroundColor: currentColor,
                    color: textColor ?? Utils.Color.getTextColorFromHex(currentColor),
                }}
            />
            <Flex
                items="center"
                justify="center"
                rounded="xl"
                size="full"
                textSize="xs"
                border
                className="select-none"
                px="2.5"
                position="relative"
                style={{ borderColor: currentColor }}
            >
                {name}
            </Flex>
        </Box>
    );

    if (compact) {
        return (
            <Popover.Root open={expanded} onOpenChange={setExpanded}>
                <Popover.Anchor asChild>
                    <button
                        type="button"
                        data-compact-label=""
                        aria-label={name}
                        aria-expanded={expanded}
                        className={cn(
                            "inline-flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px]",
                            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        )}
                        style={{ backgroundColor: currentColor, borderColor: currentColor }}
                        onPointerDown={(event) => event.stopPropagation()}
                        onPointerEnter={(event) => {
                            if (event.pointerType !== "touch") setExpanded(true);
                        }}
                        onPointerLeave={(event) => {
                            if (event.pointerType !== "touch") setExpanded(false);
                        }}
                        onKeyDown={(event) => {
                            if (event.key !== "Escape" || !expanded) return;
                            event.preventDefault();
                            event.stopPropagation();
                            setExpanded(false);
                        }}
                        onFocus={() => setExpanded(true)}
                        onBlur={() => setExpanded(false)}
                        onClick={(event) => {
                            event.stopPropagation();
                            setExpanded(true);
                        }}
                    >
                        {emoji || null}
                    </button>
                </Popover.Anchor>
                <Popover.Content
                    side="right"
                    align="center"
                    sideOffset={-20}
                    aria-label={name}
                    data-compact-label-preview=""
                    onKeyDown={(event) => {
                        if (event.key !== "Escape") return;
                        event.preventDefault();
                        event.stopPropagation();
                        setExpanded(false);
                    }}
                    className={cn(
                        "pointer-events-none w-auto max-w-[min(20rem,calc(100vw-2rem))]",
                        "rounded-full border-0 bg-transparent p-0 shadow-none motion-reduce:!animate-none"
                    )}
                    onOpenAutoFocus={(event) => event.preventDefault()}
                    onCloseAutoFocus={(event) => event.preventDefault()}
                    onPointerDown={(event) => event.stopPropagation()}
                    onClick={(event) => event.stopPropagation()}
                >
                    <LabelBadge name={name} color={color} textColor={textColor} description={description} noTooltip />
                </Popover.Content>
            </Popover.Root>
        );
    }

    if (noTooltip) {
        return badge;
    }

    return (
        <Tooltip.Root>
            <Tooltip.Trigger asChild>{badge}</Tooltip.Trigger>
            <Tooltip.Content side="bottom">{currentDescription}</Tooltip.Content>
        </Tooltip.Root>
    );
});

export interface ILabelModelBadgeProps {
    model: TLabelModel<TLabelModelName>;
    compact?: boolean;
}

const BasicLabelModelBadge = memo(({ model, compact }: ILabelModelBadgeProps) => {
    const name = model.useField("name");
    const color = model.useField("color");
    const description = model.useField("description");

    return <LabelBadge name={name} color={color} description={description} compact={compact} />;
});

const GlobalProjectLabelBadge = ({ model, compact }: { model: ProjectLabel.TModel; compact?: boolean }) => {
    const name = model.useField("name");
    const color = model.useField("color");
    const description = model.useField("description");
    const display = model.useField("global_display");
    const { i18n } = useTranslation();
    return <LabelBadge {...globalLabelDisplay(name, description, display, i18n.language)} color={color} compact={compact} emoji={display?.emoji} />;
};

export const LabelModelBadge = memo(({ model, compact }: ILabelModelBadgeProps) =>
    model instanceof ProjectLabel.Model ? (
        <GlobalProjectLabelBadge model={model} compact={compact} />
    ) : (
        <BasicLabelModelBadge model={model} compact={compact} />
    )
);
