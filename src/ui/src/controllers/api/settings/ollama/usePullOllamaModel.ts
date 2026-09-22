import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { EOllamaModelPullStatus } from "@/core/constants/OllamaModelPull";

export interface IOllamaModelPull {
    uid: string;
    model: string;
    status: EOllamaModelPullStatus;
    percent: number;
    attempt: number;
    status_text?: string | null;
    error?: string | null;
}

const usePullOllamaModel = () => {
    const { mutate } = useQueryMutation();

    return mutate<{ model: string }, IOllamaModelPull>(["pull-ollama-model"], async ({ model }) => {
        const res = await api.post<IOllamaModelPull>(Routing.API.SETTINGS.OLLAMA.PULL_MODEL, { model });
        return res.data;
    });
};

export default usePullOllamaModel;
