import { formatNumber } from "@/core/utils/LocaleFormat";
import { useTranslation } from "react-i18next";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Progress from "@/components/base/Progress";
import Separator from "@/components/base/Separator";
import Toast from "@/components/base/Toast";
import Tooltip from "@/components/base/Tooltip";
import useGetOllamaModelList from "@/controllers/api/settings/ollama/useGetOllamaModelList";
import usePullOllamaModelHandlers from "@/controllers/socket/settings/ollama/usePullOllamaModelHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { useSocket } from "@/core/providers/SocketProvider";
import { updateProgressCallback, useOllamaPullingModel, useOllamaPullingModelProgress } from "@/core/stores/OllamaModelStore";
import { useEffect, useRef } from "react";

export interface IOllamaModelTrackerProps {
    name: string;
}

function OllamaModelTracker({ name }: IOllamaModelTrackerProps) {
    const [, i18n] = useTranslation();
    const socket = useSocket();
    const progress = useOllamaPullingModelProgress(name);
    const model = useOllamaPullingModel(name);
    const { mutateAsync: getOllamaModelListMutateAsync } = useGetOllamaModelList();
    const handlers = usePullOllamaModelHandlers({
        callback: updateProgressCallback({
            name,
            onSuccess: () => {
                getOllamaModelListMutateAsync({});
            },
            onError: (message: string) => {
                Toast.Add.error(message);
            },
        }),
    });
    const isSentRef = useRef(false);
    useSwitchSocketHandlers({ socket, handlers });

    useEffect(() => {
        if (!model || isSentRef.current) {
            return;
        }

        handlers.send({ model: name });
        isSentRef.current = true;
    }, []);

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
                    {formatNumber(progress / 100, i18n.language, { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                </Box>
            </Box>
        </Flex>
    );
}

export default OllamaModelTracker;
