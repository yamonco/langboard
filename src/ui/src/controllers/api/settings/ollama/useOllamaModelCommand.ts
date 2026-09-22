import { Routing } from "@langboard/core/constants";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";

type TOllamaModelCommand = { action: "copy"; model: string; copy_to: string } | { action: "delete"; model: string };

const useOllamaModelCommand = () => {
    const { mutate } = useQueryMutation();

    return mutate(["ollama-model-command"], async (command: TOllamaModelCommand) => {
        if (command.action === "copy") {
            await api.post(Routing.API.SETTINGS.OLLAMA.COPY_MODEL, {
                model: command.model,
                copy_to: command.copy_to,
            });
        } else {
            await api.delete(Routing.API.SETTINGS.OLLAMA.DELETE_MODEL, {
                data: { model: command.model },
            });
        }
    });
};

export default useOllamaModelCommand;
