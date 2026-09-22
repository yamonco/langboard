import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import usePullOllamaModel from "@/controllers/api/settings/ollama/usePullOllamaModel";
import { EOllamaModelPullStatus } from "@/core/constants/OllamaModelPull";
import { getOllamaModelStore } from "@/core/stores/OllamaModelStore";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

function OllamaPullModelButton() {
    const [t] = useTranslation();
    const { mutateAsync: requestPull, isPending } = usePullOllamaModel();
    const inputRef = useRef<HTMLInputElement>(null);
    const [isOpened, setIsOpened] = useState(false);
    const pull = async () => {
        if (!inputRef.current) {
            return;
        }

        const value = inputRef.current.value.trim();
        if (!value) {
            inputRef.current.focus();
            return;
        }

        try {
            const accepted = await requestPull({ model: value });
            if ([EOllamaModelPullStatus.Pending, EOllamaModelPullStatus.Queued, EOllamaModelPullStatus.Running].includes(accepted.status)) {
                getOllamaModelStore().upsertPullingModel({ name: accepted.model, isTracking: true, progress: accepted.percent });
            }
            setIsOpened(false);
        } catch {
            inputRef.current?.focus();
        }
    };

    return (
        <Popover.Root modal open={isOpened} onOpenChange={setIsOpened}>
            <Popover.Trigger asChild>
                <Button variant="outline" className="mt-4 w-full border-dashed" onClick={() => setTimeout(() => inputRef.current?.focus(), 100)}>
                    {t("settings.Pull a model")}
                </Button>
            </Popover.Trigger>
            <Popover.Content>
                <Flex direction="col" gap="3">
                    <Floating.LabelInput label={t("settings.Model name")} autoFocus autoComplete="off" disabled={false} ref={inputRef} />
                    <SubmitButton type="button" isValidating={isPending} onClick={pull}>
                        {t("settings.Pull")}
                    </SubmitButton>
                </Flex>
            </Popover.Content>
        </Popover.Root>
    );
}

export default OllamaPullModelButton;
