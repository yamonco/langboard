import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { getOllamaModelStore } from "@/core/stores/OllamaModelStore";
import { EOllamaModelPullStatus } from "@/core/constants/OllamaModelPull";
import { IOllamaModelPull } from "./usePullOllamaModel";

const useGetOllamaModelPulls = () => {
    const { mutate } = useQueryMutation();

    return mutate<Record<string, never>, IOllamaModelPull[]>(["get-ollama-model-pulls"], async () => {
        const res = await api.get<{ pulls: IOllamaModelPull[] }>(Routing.API.SETTINGS.OLLAMA.PULL_MODEL, {
            env: { interceptToast: false } as never,
        });
        const pulls = res.data.pulls;
        getOllamaModelStore().replacePullingModels(
            pulls
                .filter((pull) =>
                    [EOllamaModelPullStatus.Pending, EOllamaModelPullStatus.Queued, EOllamaModelPullStatus.Running].includes(pull.status)
                )
                .map((pull) => ({ name: pull.model, progress: pull.percent, isTracking: true }))
        );
        return pulls;
    });
};

export default useGetOllamaModelPulls;
