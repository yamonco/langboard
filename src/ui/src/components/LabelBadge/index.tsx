import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Tooltip from "@/components/base/Tooltip";
import { IModelMap, TPickedModel } from "@/core/models/ModelRegistry";
import { Utils } from "@langboard/core/utils";
import { memo } from "react";
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
}

export const LabelBadge = memo(({ name, color, textColor, description, noTooltip }: ILabelBadgeProps) => {
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
}

const BasicLabelModelBadge = memo(({ model }: ILabelModelBadgeProps) => {
    const name = model.useField("name");
    const color = model.useField("color");
    const description = model.useField("description");

    return <LabelBadge name={name} color={color} description={description} />;
});

const GlobalProjectLabelBadge = ({ model }: { model: ProjectLabel.TModel }) => {
    const name = model.useField("name");
    const color = model.useField("color");
    const description = model.useField("description");
    const display = model.useField("global_display");
    const { i18n } = useTranslation();
    return <LabelBadge {...globalLabelDisplay(name, description, display, i18n.language)} color={color} />;
};

export const LabelModelBadge = memo(({ model }: ILabelModelBadgeProps) =>
    model instanceof ProjectLabel.Model ? <GlobalProjectLabelBadge model={model} /> : <BasicLabelModelBadge model={model} />
);
