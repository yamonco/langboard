/* eslint-disable @typescript-eslint/no-explicit-any */
import { IPullOllamaModelResponse } from "@/controllers/socket/settings/ollama/usePullOllamaModelHandlers";
import { Utils } from "@langboard/core/utils";
import { useEffect, useState } from "react";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

export type TBaseOllamaModel = {
    name: string;
    size: number;
    digest: string;
    modified_at: Date;
    details: {
        parent_model?: string;
        format: string;
        family: string;
        families: string[] | null;
        parameter_size: string;
        quantization_level: string;
    };
    modelfile?: string;
    parameters?: string;
    template?: string;
    model_info?: {
        [key: string]: string | number | string[];
    };
    capabilities?: string[];
    expires_at?: Date;
    size_vram?: number;
    is_running?: bool;
};

interface IBaseOllamaModel {
    isTracking: bool;
    name: string;
    progress?: number;
}

interface IUntrackedOllamaModel extends IBaseOllamaModel {
    isTracking: false;
}

interface ITrackedOllamaModel extends IBaseOllamaModel {
    isTracking: true;
}

export type TOllamaPullingModel = IUntrackedOllamaModel | ITrackedOllamaModel;

interface IOllamaModelStore {
    models: Record<string, TBaseOllamaModel>;
    pullingModels: Record<string, TOllamaPullingModel>;
    upsertModel: (model: TBaseOllamaModel) => void;
    deleteModel: (name: string) => void;
    replaceModels: (models: TBaseOllamaModel[]) => void;
    upsertPullingModel: (model: TOllamaPullingModel) => void;
    deletePullingModel: (name: string) => void;
    replacePullingModels: (models: (string | TOllamaPullingModel)[]) => void;
}

const useOllamaModelStore = create(
    immer<IOllamaModelStore>((set, get) => {
        return {
            models: {},
            pullingModels: {},
            upsertModel: (model: TBaseOllamaModel) => {
                const currentModels = get().models;
                currentModels[model.name] = {
                    ...(currentModels[model.name] || {}),
                    ...model,
                } as any;
                set({ models: currentModels });
            },
            deleteModel: (name: string) => {
                const currentModels = get().models;
                delete currentModels[name];
                set({ models: currentModels });
            },
            replaceModels: (models: TBaseOllamaModel[]) => {
                const newModels: Record<string, TBaseOllamaModel> = {};
                models.forEach((model) => {
                    newModels[model.name] = model;
                });
                set({ models: newModels });
            },
            upsertPullingModel: (model: TOllamaPullingModel) => {
                const currentModels = get().pullingModels;
                currentModels[model.name] = {
                    ...(currentModels[model.name] || {}),
                    ...model,
                } as any;
                set({ pullingModels: currentModels });
            },
            deletePullingModel: (name: string) => {
                const currentModels = get().pullingModels;
                delete currentModels[name];
                set({ pullingModels: currentModels });
            },
            replacePullingModels: (models: (string | TOllamaPullingModel)[]) => {
                const newModels: Record<string, TOllamaPullingModel> = {};
                models.forEach((model) => {
                    if (Utils.Type.isString(model)) {
                        newModels[model] = { name: model, progress: 0, isTracking: true };
                    } else {
                        newModels[model.name] = model;
                    }
                });
                set({ pullingModels: newModels });
            },
        };
    })
);

export const getOllamaModelStore = () => useOllamaModelStore.getState();

export const useOllamaModel = (name: string): TBaseOllamaModel | undefined => {
    const [model, setModel] = useState(getOllamaModelStore().models[name]);

    useEffect(() => {
        const off = useOllamaModelStore.subscribe((state) => {
            const newModel = state.models[name];
            if (Object.keys(model || {}).length !== Object.keys(newModel || {}).length) {
                setModel(newModel);
                return;
            }

            const entries = Object.entries(model || {});
            for (let i = 0; i < entries.length; ++i) {
                const [k, v] = entries[i];
                if (newModel?.[k] !== v) {
                    setModel(newModel);
                    return;
                }
            }
        });

        return off;
    }, [model, setModel, name]);

    return model;
};

export const useOllamaPullingModel = (name: string): TOllamaPullingModel | undefined => {
    const [model, setModel] = useState(getOllamaModelStore().pullingModels[name]);

    useEffect(() => {
        const off = useOllamaModelStore.subscribe((state) => {
            const newModel = state.pullingModels[name];
            if (Object.keys(model || {}).length !== Object.keys(newModel || {}).length) {
                setModel(newModel);
                return;
            }

            const entries = Object.entries(model || {});
            for (let i = 0; i < entries.length; ++i) {
                const [k, v] = entries[i];
                if (newModel?.[k] !== v) {
                    setModel(newModel);
                    return;
                }
            }
        });

        return off;
    }, [model, setModel, name]);

    return model;
};

export const useOllamaPullingModelProgress = (name: string): number => {
    const [progress, setProgress] = useState(getOllamaModelStore().pullingModels[name]?.progress || 0);

    useEffect(() => {
        const off = useOllamaModelStore.subscribe((state) => {
            const newProgress = state.pullingModels[name]?.progress || 0;
            if (newProgress !== progress) {
                setProgress(newProgress);
            }
        });

        return off;
    }, [progress, setProgress, name]);

    return progress;
};

export const updateProgressCallback =
    ({ onSuccess, onError }: { onSuccess: () => void; onError: (message: string) => void }) =>
    (data: IPullOllamaModelResponse) => {
        const name = data.model;

        if (data.percent) {
            getOllamaModelStore().upsertPullingModel({ name, progress: data.percent, isTracking: true });
        }

        if (data.status === "error") {
            getOllamaModelStore().deletePullingModel(name);
            onError(data.error || "Unknown error");
        }

        if (data.status === "success") {
            getOllamaModelStore().deletePullingModel(name);
            onSuccess();
        }
    };

export default useOllamaModelStore;
