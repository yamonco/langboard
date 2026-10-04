import assert from "node:assert/strict";
import { test } from "node:test";
import { getOllamaModelStore, TBaseOllamaModel } from "./OllamaModelStore";

test("model and pull mutations preserve prior store snapshots", () => {
    const model: TBaseOllamaModel = {
        name: "store-test-model",
        size: 1,
        digest: "digest",
        modified_at: new Date(0),
        details: {
            format: "gguf",
            family: "test",
            families: null,
            parameter_size: "1B",
            quantization_level: "Q4",
        },
    };
    const previousModels = getOllamaModelStore().models;
    const previousPulls = getOllamaModelStore().pullingModels;

    try {
        getOllamaModelStore().upsertModel(model);
        const withModel = getOllamaModelStore().models;
        assert.notStrictEqual(withModel, previousModels);
        assert.equal(previousModels[model.name], undefined);
        assert.deepEqual(withModel[model.name], model);

        getOllamaModelStore().upsertPullingModel({ name: model.name, isTracking: true, progress: 20 });
        const withPull = getOllamaModelStore().pullingModels;
        assert.notStrictEqual(withPull, previousPulls);
        assert.equal(previousPulls[model.name], undefined);
        assert.equal(withPull[model.name]?.progress, 20);

        getOllamaModelStore().deletePullingModel(model.name);
        assert.equal(getOllamaModelStore().pullingModels[model.name], undefined);
        assert.equal(withPull[model.name]?.progress, 20);

        getOllamaModelStore().deleteModel(model.name);
        assert.equal(getOllamaModelStore().models[model.name], undefined);
        assert.deepEqual(withModel[model.name], model);
    } finally {
        getOllamaModelStore().deletePullingModel(model.name);
        getOllamaModelStore().deleteModel(model.name);
    }
});
