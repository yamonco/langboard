import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Tooltip from "@/components/base/Tooltip";
import useGetOllamaModelList from "@/controllers/api/settings/ollama/useGetOllamaModelList";
import useOllamaModelCommand from "@/controllers/api/settings/ollama/useOllamaModelCommand";
import useCopyOllamaModelHandlers from "@/controllers/socket/settings/ollama/useCopyOllamaModelHandlers";
import useDeleteOllamaModelHandlers from "@/controllers/socket/settings/ollama/useDeleteOllamaModelHandlers";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { useSocket } from "@/core/providers/SocketProvider";
import { getOllamaModelStore, useOllamaModel } from "@/core/stores/OllamaModelStore";
import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IOllamaModelListItemProps {
    name: string;
}

function OllamaModelListItem({ name }: IOllamaModelListItemProps) {
    const socket = useSocket();
    const [t] = useTranslation();
    const model = useOllamaModel(name);
    const { mutateAsync: getOllamaModelListMutateAsync } = useGetOllamaModelList();
    const isRunning = model?.is_running;
    const copiedHandlers = useCopyOllamaModelHandlers({
        callback: (data) => {
            if (data.model !== name) {
                return;
            }

            getOllamaModelListMutateAsync({});
        },
    });
    const deletedHandlers = useDeleteOllamaModelHandlers({
        callback: (data) => {
            if (data.model !== name) {
                return;
            }

            getOllamaModelStore().deleteModel(name);
        },
    });
    const handlers = useMemo(() => [copiedHandlers, deletedHandlers], [copiedHandlers, deletedHandlers]);
    useSwitchSocketHandlers({ socket, handlers });

    if (!model) {
        return null;
    }

    return (
        <Flex gap="2" justify="between" items="center" py="2" px="3" border rounded="md">
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <Flex gap="2" items="center">
                        <Box maxW="48" className="truncate">
                            {model.name}
                        </Box>
                        {isRunning && (
                            <Box weight="semibold" textSize="sm" className="text-green-500/70">
                                ({t("settings.Running")})
                            </Box>
                        )}
                    </Flex>
                </Tooltip.Trigger>
                <Tooltip.Content>{model.name}</Tooltip.Content>
            </Tooltip.Root>
            <Flex gap="2" items="center">
                <OllamaModelListItemCopyButton name={name} />
                <OllamaModelListItemDeleteButton name={name} />
            </Flex>
        </Flex>
    );
}

function OllamaModelListItemCopyButton({ name }: { name: string }) {
    const [t] = useTranslation();
    const inputRef = useRef<HTMLInputElement>(null);
    const [isOpened, setIsOpened] = useState(false);
    const { mutateAsync: command } = useOllamaModelCommand();
    const { mutateAsync: getOllamaModelList } = useGetOllamaModelList();
    const [isValidating, setIsValidating] = useState(false);
    const save = async () => {
        if (isValidating || !inputRef.current) {
            return;
        }

        setIsValidating(true);

        const value = inputRef.current.value.trim();
        if (!value) {
            setIsValidating(false);
            inputRef.current.focus();
            return;
        }

        try {
            await command({ action: "copy", model: name, copy_to: value });
            setIsOpened(false);
        } catch {
            return;
        } finally {
            setIsValidating(false);
            void getOllamaModelList({}).catch(() => undefined);
        }
    };

    return (
        <Popover.Root modal open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <Button size="icon-sm" variant="outline" title={t("common.Copy")}>
                    <IconComponent icon="copy" size="4" />
                </Button>
            </Popover.Trigger>
            <Popover.Content>
                <Flex direction="col" gap="3">
                    <Floating.LabelInput label={t("settings.Model name")} autoFocus autoComplete="off" disabled={false} ref={inputRef} />
                    <SubmitButton type="button" isValidating={isValidating} onClick={save}>
                        {t("common.Copy")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

function OllamaModelListItemDeleteButton({ name }: { name: string }) {
    const [t] = useTranslation();
    const inputRef = useRef<HTMLInputElement>(null);
    const [isOpened, setIsOpened] = useState(false);
    const { mutateAsync: command } = useOllamaModelCommand();
    const { mutateAsync: getOllamaModelList } = useGetOllamaModelList();
    const [isValidating, setIsValidating] = useState(false);
    const deleteModel = async () => {
        if (isValidating || !inputRef.current) {
            return;
        }

        setIsValidating(true);

        const value = inputRef.current.value.trim();
        if (!value) {
            setIsValidating(false);
            inputRef.current.focus();
            return;
        }

        try {
            await command({ action: "delete", model: name });
            setIsOpened(false);
        } catch {
            return;
        } finally {
            setIsValidating(false);
            void getOllamaModelList({}).catch(() => undefined);
        }
    };

    return (
        <Popover.Root modal open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <Button size="icon-sm" variant="destructive" title={t("common.Delete")}>
                    <IconComponent icon="trash" size="4" />
                </Button>
            </Popover.Trigger>
            <Popover.Content className="w-auto min-w-0 max-w-xs sm:max-w-sm md:max-w-md lg:max-w-lg">
                <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                    {t("ask.Are you sure you want to delete this model?")}
                </Box>
                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                    {t("common.deleteDescriptions.All data will be lost.")}
                </Box>
                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                    {t("common.deleteDescriptions.This action cannot be undone.")}
                </Box>
                <Flex items="center" justify="end" gap="1" mt="2">
                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => setIsOpened(false)}>
                        {t("common.Cancel")}
                    </Button>
                    <SubmitButton type="button" size="sm" variant="destructive" onClick={deleteModel} isValidating={isValidating}>
                        {t("common.Delete")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

export default OllamaModelListItem;
