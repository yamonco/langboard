import Flex from "@/components/base/Flex";
import Toast from "@/components/base/Toast";
import useGetOllamaModelList from "@/controllers/api/settings/ollama/useGetOllamaModelList";
import useGetOllamaModelPulls from "@/controllers/api/settings/ollama/useGetOllamaModelPulls";
import useGetOllamaRunningModelList from "@/controllers/api/settings/ollama/useGetOllamaRunningModelList";
import usePullOllamaModelHandlers from "@/controllers/socket/settings/ollama/usePullOllamaModelHandlers";
import { EOllamaModelPullStatus } from "@/core/constants/OllamaModelPull";
import useSwitchSocketHandlers from "@/core/hooks/useSwitchSocketHandlers";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { useSocket } from "@/core/providers/SocketProvider";
import { getOllamaModelStore, updateProgressCallback } from "@/core/stores/OllamaModelStore";
import OllamaModelList from "@/pages/SettingsPage/components/ollama/OllamaModelList";
import OllamaModelTrackingList from "@/pages/SettingsPage/components/ollama/OllamaModelTrackingList";
import OllamaPullModelButton from "@/pages/SettingsPage/components/ollama/OllamaPullModelButton";
import { ESocketTopic, GLOBAL_TOPIC_ID } from "@langboard/core/enums";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

function OllamaPage() {
    const socket = useSocket();
    const { setPageAliasRef } = usePageHeader();
    const [t] = useTranslation();
    const { mutateAsync: getOllamaModelListMutateAsync } = useGetOllamaModelList();
    const { mutateAsync: getOllamaModelPullsMutateAsync } = useGetOllamaModelPulls();
    const { mutateAsync: getOllamaRunningModelListMutateAsync } = useGetOllamaRunningModelList();
    const handlers = usePullOllamaModelHandlers({
        callback: updateProgressCallback({
            onSuccess: () => {
                void getOllamaModelListMutateAsync({});
            },
            onError: (message) => Toast.Add.error(message),
        }),
    });
    useSwitchSocketHandlers({ socket, handlers });

    useEffect(() => {
        setPageAliasRef.current("Ollama");
        let isMounted = true;
        let isReconciling = false;

        socket.subscribe(ESocketTopic.OllamaManager, [GLOBAL_TOPIC_ID]);

        const reconcilePulls = async () => {
            if (isReconciling) {
                return;
            }
            isReconciling = true;
            try {
                const tracked = getOllamaModelStore().pullingModels;
                const pulls = await getOllamaModelPullsMutateAsync({});
                if (!isMounted) {
                    return;
                }
                for (const pull of pulls) {
                    if (!tracked[pull.model]) {
                        continue;
                    }
                    if (pull.status === EOllamaModelPullStatus.Success) {
                        await getOllamaModelListMutateAsync({});
                    } else if (pull.status === EOllamaModelPullStatus.Failed || pull.status === EOllamaModelPullStatus.Uncertain) {
                        Toast.Add.error(pull.error || "Model pull could not be completed");
                    }
                }
            } catch {
                // Keep the last known progress until the next reconciliation attempt.
            } finally {
                isReconciling = false;
            }
        };

        const fetchModels = async () => {
            await Promise.allSettled([getOllamaModelListMutateAsync({}), getOllamaRunningModelListMutateAsync({})]);
            await reconcilePulls();
        };

        void fetchModels();
        const interval = setInterval(() => {
            void reconcilePulls();
        }, 5000);

        return () => {
            isMounted = false;
            clearInterval(interval);
            socket.unsubscribe(ESocketTopic.OllamaManager, [GLOBAL_TOPIC_ID]);
        };
    }, []);

    return (
        <>
            <Flex justify="between" mb="4" pb="2" textSize="3xl" weight="semibold" className="scroll-m-20 border-b tracking-tight">
                <span className="w-36">{t("settings.Ollama")}</span>
            </Flex>
            <OllamaModelList />
            <OllamaModelTrackingList />
            <OllamaPullModelButton />
        </>
    );
}
OllamaPage.displayName = "OllamaPage";

export default OllamaPage;
