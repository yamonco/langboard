import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Progress from "@/components/base/Progress";
import Separator from "@/components/base/Separator";
import Tooltip from "@/components/base/Tooltip";
import { useOllamaPullingModel, useOllamaPullingModelProgress } from "@/core/stores/OllamaModelStore";

export interface IOllamaModelTrackerProps {
    name: string;
}

function OllamaModelTracker({ name }: IOllamaModelTrackerProps) {
    const progress = useOllamaPullingModelProgress(name);
    const model = useOllamaPullingModel(name);

    if (!model) {
        return null;
    }

    return (
        <Flex gap="2" items="center" py="2" px="3" border rounded="md">
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <Box w="48" className="truncate">
                        {model.name}
                    </Box>
                </Tooltip.Trigger>
                <Tooltip.Content>{model.name}</Tooltip.Content>
            </Tooltip.Root>
            <Separator orientation="vertical" className="h-6" />
            <Box w="full" position="relative">
                <Progress value={progress} className="w-full" />
                <Box position="absolute" textSize="sm" className="left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
                    {progress.toFixed?.(2) ?? "0.00"}%
                </Box>
            </Box>
        </Flex>
    );
}

export default OllamaModelTracker;
