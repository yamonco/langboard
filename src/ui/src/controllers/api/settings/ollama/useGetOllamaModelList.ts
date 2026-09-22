import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { TMutationOptions, useQueryMutation } from "@/core/helpers/QueryMutation";
import { getOllamaModelStore, TBaseOllamaModel } from "@/core/stores/OllamaModelStore";

const useGetOllamaModelList = (options?: TMutationOptions) => {
    const { mutate } = useQueryMutation();

    const getOllamaModelList = async () => {
        const res = await api.get<{
            models: TBaseOllamaModel[];
        }>(Routing.API.SETTINGS.OLLAMA.GET_LIST, {
            env: {
                interceptToast: options?.interceptToast,
            } as never,
        });

        for (let i = 0; i < res.data.models.length; ++i) {
            res.data.models[i].modified_at = new Date(res.data.models[i].modified_at);
        }

        getOllamaModelStore().replaceModels(res.data.models);
        return res.data;
    };

    const result = mutate(["get-ollama-model-list"], getOllamaModelList, {
        ...options,
        retry: 0,
    });

    return result;
};

export default useGetOllamaModelList;
