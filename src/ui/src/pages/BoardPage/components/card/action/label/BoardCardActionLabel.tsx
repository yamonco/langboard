import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Tooltip from "@/components/base/Tooltip";
import { ProjectLabel } from "@/core/models";
import { globalLabelDisplay } from "@/core/utils/LabelDisplay";
import { useTranslation } from "react-i18next";
import { memo } from "react";

export interface IBoardCardActionLabelProps {
    label: ProjectLabel.TModel;
}

const BoardCardActionLabel = memo(({ label }: IBoardCardActionLabelProps) => {
    const name = label.useField("name");
    const color = label.useField("color");
    const description = label.useField("description");
    const snapshot = label.useField("global_display");
    const { i18n } = useTranslation();
    const display = globalLabelDisplay(name, description, snapshot, i18n.language);

    return (
        <Tooltip.Root>
            <Tooltip.Trigger asChild>
                <Flex items="center" gap="1.5" className="truncate">
                    <Box
                        minH="6"
                        minW="6"
                        rounded="md"
                        style={{
                            backgroundColor: color || "#FFFFFF",
                        }}
                    />
                    <Box className="truncate">{display.name}</Box>
                </Flex>
            </Tooltip.Trigger>
            <Tooltip.Content align="center">{display.description}</Tooltip.Content>
        </Tooltip.Root>
    );
});

export default BoardCardActionLabel;
