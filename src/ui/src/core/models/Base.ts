/* eslint-disable @typescript-eslint/no-explicit-any */

import { create, StoreApi, UseBoundStore } from "zustand";
import { immer } from "zustand/middleware/immer";
import { produce } from "immer";
import { useEffect, useState } from "react";
import { Utils } from "@langboard/core/utils";
import createFakeModel from "@/core/models/FakeModel";
import { ModelRegistry, IModelMap, TPickedModel } from "@/core/models/ModelRegistry";
import {
    getForeignModelArray,
    pickForeignModels,
    syncForeignModelEdges,
    useForeignModelArray,
    useForeignModelOne,
} from "@/core/models/base/modelEdges";
import {
    clearModelSocketSubscriptions,
    subscribeModelSocketEvents,
    TModelSocketHandlerFactory,
    unsubscribeModelSocketEvents,
} from "@/core/models/base/socketSubscriptions";

export interface IEditorContent {
    content: string;
}

export interface IGraphInterruptContent {
    id?: string | null;
    value?: string | number | bool | Record<string, unknown> | unknown[] | null;
}

export interface IChatContent {
    content: string;
    graph_interrupt?: IGraphInterruptContent | null;
    graph_resume_error?: string | null;
}

export interface IBaseModel {
    uid: string;
    created_at: Date;
    updated_at: Date;
}

export type TStateStore<T = any, V = undefined> = V extends undefined
    ? UseBoundStore<StoreApi<T>>
    : UseBoundStore<StoreApi<Omit<T, keyof V>>> & {
          [K in keyof V]: Record<string, UseBoundStore<StoreApi<V[K]>>>;
      };

export interface IModelNotifiersMap {
    CREATION: Partial<Record<keyof IModelMap, Record<string, [(model: BaseModel<any>) => bool, (models: BaseModel<any>[]) => void]>>>;
    DELETION: Partial<Record<keyof IModelMap, Record<string, (uids: string[]) => void>>>;
}

type TModelStoreMap = {
    [TModelName in keyof IModelMap]: {
        [uid: string]: TPickedModel<TModelName>;
    };
};

export abstract class BaseModel<TModel extends IBaseModel> {
    static readonly #MODELS: Partial<TModelStoreMap> = {};
    static readonly #NOTIFIERS: IModelNotifiersMap = {
        CREATION: {},
        DELETION: {},
    };
    #store: TStateStore<TModel>;

    public static get FOREIGN_MODELS(): Record<string, keyof IModelMap> {
        return {};
    }

    public static get MODEL_NAME(): keyof IModelMap {
        return this.constructor.name as any;
    }

    constructor(model: Record<string, any>) {
        const foreignModels = pickForeignModels(model, this.#getConstructor().FOREIGN_MODELS);
        this.#store = create(
            immer(() => ({
                ...model,
            }))
        ) as any;
        syncForeignModelEdges({
            source: this as any,
            model: foreignModels,
            foreignModels: this.#getConstructor().FOREIGN_MODELS,
            isModelInstance: (value): value is TPickedModel<keyof IModelMap> => value instanceof BaseModel,
        });
    }

    public static fromOne<TDerived extends typeof BaseModel<any>, TModel extends IBaseModel>(
        this: TDerived,
        model: Partial<TModel> & IBaseModel,
        shouldNotify: true,
        createdModels?: never
    ): InstanceType<TDerived>;
    public static fromOne<TDerived extends typeof BaseModel<any>, TModel extends IBaseModel>(
        this: TDerived,
        model: Partial<TModel> & IBaseModel,
        shouldNotify?: false,
        createdModels?: TPickedModel<keyof IModelMap>[]
    ): InstanceType<TDerived>;
    public static fromOne<TDerived extends typeof BaseModel<any>, TModel extends IBaseModel>(
        this: TDerived,
        model: Partial<TModel> & IBaseModel,
        shouldNotify: bool = false,
        createdModels?: TPickedModel<keyof IModelMap>[]
    ) {
        const modelName = this.MODEL_NAME;
        if (!BaseModel.#MODELS[modelName]) {
            BaseModel.#MODELS[modelName] = {};
        }

        const targetModelMap = BaseModel.#MODELS[modelName];

        model = { ...model };

        if (Utils.Type.isString(model.created_at)) {
            model.created_at = new Date(model.created_at);
        }
        if (Utils.Type.isString(model.updated_at)) {
            model.updated_at = new Date(model.updated_at);
        }

        if (!targetModelMap[model.uid]) {
            model = this.convertModel(model);
            targetModelMap[model.uid] = new (this as any)(model);
            const targetModel = targetModelMap[model.uid];
            if (shouldNotify) {
                BaseModel.#notify("CREATION", modelName, targetModel);
            } else {
                if (createdModels) {
                    createdModels.push(targetModel);
                }
            }
        } else {
            (targetModelMap[model.uid] as any).update(model);
        }

        return targetModelMap[model.uid];
    }

    public static fromArray<TDerived extends typeof BaseModel<any>, TModel extends IBaseModel>(
        this: TDerived,
        models: (Partial<TModel> & IBaseModel)[],
        shouldNotify: bool = false
    ): InstanceType<TDerived>[] {
        if (!shouldNotify) {
            return models.map((model) => this.fromOne(model, false));
        }

        const createdModels: any[] = [];
        const resultModels = models.map((model) => this.fromOne(model, false, createdModels));
        if (createdModels.length > 0) {
            const modelName = this.MODEL_NAME;
            BaseModel.#notify("CREATION", modelName, createdModels);
        }
        return resultModels;
    }

    public static convertModel(model: any): any {
        return model;
    }

    public static createFakeMethodsMap<TMethodMap>(_: any): TMethodMap {
        return {} as TMethodMap;
    }

    public static subscribe<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        type: "CREATION",
        key: string,
        notifier: (models: InstanceType<TDerived>[]) => void,
        filter: (model: InstanceType<TDerived>) => bool
    ): () => void;
    public static subscribe(type: "DELETION", key: string, notifier: (uids: string[]) => void): () => void;
    public static subscribe<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        type: keyof IModelNotifiersMap,
        key: string,
        notifier: (models: InstanceType<TDerived>[]) => void,
        filter?: (model: InstanceType<TDerived>) => bool
    ) {
        const modelName = this.MODEL_NAME;
        if (!BaseModel.#NOTIFIERS[type][modelName]) {
            BaseModel.#NOTIFIERS[type][modelName] = {};
        }

        if (type === "CREATION") {
            BaseModel.#NOTIFIERS[type][modelName][key] = [filter, notifier] as any;
        } else {
            BaseModel.#NOTIFIERS[type][modelName][key] = notifier as any;
        }

        return () => {
            this.unsubscribe(type, key);
        };
    }

    public static unsubscribe(type: keyof IModelNotifiersMap, key: string) {
        const modelName = this.MODEL_NAME;
        if (!BaseModel.#NOTIFIERS[type]?.[modelName]) {
            return;
        }

        delete BaseModel.#NOTIFIERS[type][modelName][key];
    }

    public static getModel<TDerived extends typeof BaseModel<any>>(this: TDerived, uid: string): InstanceType<TDerived> | undefined;
    public static getModel<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        filter: (model: InstanceType<TDerived>) => bool
    ): InstanceType<TDerived> | undefined;
    public static getModel<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        uidOrFilter: string | ((model: InstanceType<TDerived>) => bool)
    ): InstanceType<TDerived> | undefined {
        if (Utils.Type.isString(uidOrFilter)) {
            return BaseModel.#MODELS[this.MODEL_NAME]?.[uidOrFilter] as any;
        }

        const models = Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {});
        for (let i = 0; i < models.length; ++i) {
            if (uidOrFilter(models[i] as any)) {
                return models[i] as any;
            }
        }
        return undefined;
    }

    public static getModels<TDerived extends typeof BaseModel<any>>(this: TDerived, uids: string[]): InstanceType<TDerived>[];
    public static getModels<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        filter: (model: InstanceType<TDerived>) => bool
    ): InstanceType<TDerived>[];
    public static getModels<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        uidsOrFilter: string[] | ((model: InstanceType<TDerived>) => bool)
    ): InstanceType<TDerived>[] {
        const models: InstanceType<TDerived>[] = [];
        if (Utils.Type.isFunction(uidsOrFilter)) {
            return Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {}).filter(uidsOrFilter as any);
        }

        for (let i = 0; i < uidsOrFilter.length; ++i) {
            const model = BaseModel.#MODELS[this.MODEL_NAME]?.[uidsOrFilter[i]];
            if (model) {
                models.push(model as any);
            }
        }
        return models;
    }

    public static useModel<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        uidOrFilter: string | ((model: InstanceType<TDerived>) => bool),
        dependencies?: React.DependencyList
    ): InstanceType<TDerived> | undefined {
        const filter = Utils.Type.isString(uidOrFilter) ? (model: InstanceType<TDerived>) => model.uid === uidOrFilter : uidOrFilter;
        const [model, setModel] = useState<InstanceType<TDerived> | undefined>(
            () => Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {}).filter(filter as any)[0]
        );

        useEffect(() => {
            const key = Utils.String.Token.uuid();
            const unsubscribeCreation = this.subscribe(
                "CREATION",
                key,
                (newModels) => {
                    const newModel = newModels.find(filter);
                    if (!newModel) {
                        return;
                    }

                    setModel(() => newModel);
                },
                filter
            );
            const unsubscribeDeletion = this.subscribe("DELETION", key, (uids) => {
                if (!uids.length || !model || !uids.includes(model.uid)) {
                    return;
                }

                setModel(() => undefined);
            });

            return () => {
                unsubscribeCreation();
                unsubscribeDeletion();
            };
        }, [model]);

        useEffect(() => {
            if (dependencies && dependencies.length > 0) {
                setModel(() => Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {}).filter(filter as any)[0]);
            }
        }, dependencies);

        return model;
    }

    public static useModels<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        filter: (model: InstanceType<TDerived>) => bool,
        dependencies?: React.DependencyList
    ): InstanceType<TDerived>[] {
        const [models, setModels] = useState<InstanceType<TDerived>[]>(
            () => Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {}).filter(filter as any) as any
        );

        useEffect(() => {
            const key = Utils.String.Token.uuid();
            const unsubscribeCreation = this.subscribe(
                "CREATION",
                key,
                (newModels) => {
                    if (!newModels.length) {
                        return;
                    }

                    setModels((prevModels) => [...prevModels, ...newModels]);
                },
                filter
            );
            const unsubscribeDeletion = this.subscribe("DELETION", key, (uids) => {
                if (!uids.length) {
                    return;
                }

                setModels((prevModels) => prevModels.filter((model) => !uids.includes(model.uid)));
            });

            return () => {
                unsubscribeCreation();
                unsubscribeDeletion();
            };
        }, [models]);

        useEffect(() => {
            if (dependencies && dependencies.length > 0) {
                setModels(() => Object.values(BaseModel.#MODELS[this.MODEL_NAME] ?? {}).filter(filter as any) as any);
            }
        }, dependencies);

        return models;
    }

    public static deleteModel<TDerived extends typeof BaseModel<any>>(this: TDerived, uid: string): void;
    public static deleteModel<TDerived extends typeof BaseModel<any>>(this: TDerived, filter: (model: InstanceType<TDerived>) => bool): void;
    public static deleteModel<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        uidOrFilter: string | ((model: InstanceType<TDerived>) => bool)
    ) {
        const modelName = this.MODEL_NAME;
        if (!BaseModel.#MODELS[modelName]) {
            return;
        }

        if (Utils.Type.isString(uidOrFilter)) {
            delete BaseModel.#MODELS[modelName][uidOrFilter];
        } else {
            const model = Object.values(BaseModel.#MODELS[modelName] ?? {}).find(uidOrFilter as any);
            if (model) {
                delete BaseModel.#MODELS[modelName][model.uid];
                uidOrFilter = model.uid;
            }
        }

        if (Utils.Type.isString(uidOrFilter)) {
            this.unsubscribeSocketEvents(uidOrFilter);

            BaseModel.#notify("DELETION", modelName, uidOrFilter);
        }
    }

    public static deleteModels<TDerived extends typeof BaseModel<any>>(this: TDerived, uids: string[]): void;
    public static deleteModels<TDerived extends typeof BaseModel<any>>(this: TDerived, filter: (model: InstanceType<TDerived>) => bool): void;
    public static deleteModels<TDerived extends typeof BaseModel<any>>(
        this: TDerived,
        uidsOrFilter: string[] | ((model: InstanceType<TDerived>) => bool)
    ) {
        const modelName = this.MODEL_NAME;
        if (!BaseModel.#MODELS[modelName]) {
            return;
        }

        let uids: string[] = [];
        if (Utils.Type.isArray(uidsOrFilter)) {
            for (let i = 0; i < uidsOrFilter.length; ++i) {
                const uid = uidsOrFilter[i];
                delete BaseModel.#MODELS[modelName][uid];

                this.unsubscribeSocketEvents(uid);
            }
            uids = uidsOrFilter;
        } else {
            const values = Object.values(BaseModel.#MODELS[modelName] ?? {});
            for (let i = 0; i < values.length; ++i) {
                const model = values[i];
                if (uidsOrFilter(model as any)) {
                    uids.push(model.uid);
                    delete BaseModel.#MODELS[modelName][model.uid];
                    this.unsubscribeSocketEvents(model.uid);
                }
            }
        }

        BaseModel.#notify("DELETION", modelName, uids);
    }

    public static unsubscribeSocketEvents(uid: string) {
        unsubscribeModelSocketEvents(this.MODEL_NAME, uid);
    }

    public static cleanUp() {
        const modelName = this.MODEL_NAME;

        delete BaseModel.#MODELS[modelName];
        delete BaseModel.#NOTIFIERS.CREATION[modelName];
        delete BaseModel.#NOTIFIERS.DELETION[modelName];
        clearModelSocketSubscriptions(modelName);
    }

    static #notify<TModelName extends keyof IModelMap>(
        type: "CREATION",
        modelName: TModelName,
        targetModels: TPickedModel<TModelName> | TPickedModel<TModelName>[]
    ): void;
    static #notify<TModelName extends keyof IModelMap>(type: "DELETION", modelName: TModelName, uids: string | string[]): void;
    static #notify<TModelName extends keyof IModelMap>(
        type: keyof IModelNotifiersMap,
        modelName: TModelName,
        targetModelsOrUIDs: (TPickedModel<TModelName> | string) | (TPickedModel<TModelName> | string)[]
    ) {
        const notifierMap = BaseModel.#NOTIFIERS[type]?.[modelName];
        if (!notifierMap) {
            return;
        }

        if (!Utils.Type.isArray(targetModelsOrUIDs)) {
            targetModelsOrUIDs = [targetModelsOrUIDs];
        }

        if (type === "DELETION") {
            Object.values(notifierMap).forEach((notifier) => notifier(targetModelsOrUIDs));
            return;
        }

        Object.values(notifierMap).forEach(([filter, notifier]) => {
            const filtered = targetModelsOrUIDs.filter(filter);
            if (!filtered.length) {
                return;
            }

            notifier(filtered);
        });
    }

    public get FOREIGN_MODELS(): Partial<Record<keyof TModel, keyof IModelMap>> {
        return this.#getConstructor().FOREIGN_MODELS as any;
    }

    public get uid() {
        return this.getValue("uid");
    }
    public set uid(value) {
        this.update({ uid: value });
    }

    public get created_at(): Date {
        return this.getValue("created_at");
    }
    public set created_at(value: string | Date) {
        this.update({ created_at: new Date(value) });
    }

    public get updated_at(): Date {
        return this.getValue("updated_at");
    }
    public set updated_at(value: string | Date) {
        this.update({ updated_at: new Date(value) });
    }

    public get MODEL_NAME(): keyof IModelMap {
        return this.#getConstructor().MODEL_NAME;
    }

    public asFake<TDerived extends BaseModel<any>>(this: TDerived): TDerived {
        const constructor = this.#getConstructor();
        const model = {
            ...this.#store.getState(),
        };
        const foreignModels: Record<string, any[]> = {};
        Object.keys(constructor.FOREIGN_MODELS).forEach((key) => {
            foreignModels[key] = this.getForeignValue(key).map((foreignModel) => {
                return foreignModel.asFake();
            });
        });
        return createFakeModel(constructor.MODEL_NAME, model, constructor.createFakeMethodsMap(model), foreignModels);
    }

    public useField<TKey extends keyof TModel>(
        field: TKey,
        updatedCallback?: (newValue: TModel[TKey], oldValue: TModel[TKey]) => void
    ): TModel[TKey] {
        const [fieldValue, setFieldValue] = useState<TModel[TKey]>(this.getValue(field));

        useEffect(() => {
            const unsub = this.#store.subscribe((newValue) => {
                if (newValue[field] === fieldValue) {
                    return;
                }

                setTimeout(() => {
                    setFieldValue(newValue[field]);
                    updatedCallback?.(newValue[field], fieldValue);
                }, 0);
            });

            return () => {
                unsub();
            };
        }, [fieldValue]);

        return fieldValue;
    }

    public useForeignFieldArray<TDerived extends BaseModel<TModel>, TKey extends keyof TDerived["FOREIGN_MODELS"]>(
        this: TDerived,
        field: TKey,
        dependencies?: React.DependencyList
    ) {
        type TModelName = TDerived["FOREIGN_MODELS"][TKey];
        type TForeignModel = TModelName extends keyof IModelMap ? InstanceType<IModelMap[TModelName]["Model"]> : never;
        const modelName = this.#getConstructor().FOREIGN_MODELS[field as string];
        const fieldValue = useForeignModelArray<TForeignModel>(this as any, modelName, dependencies);

        return fieldValue as TForeignModel[];
    }

    public useForeignFieldOne<TDerived extends BaseModel<TModel>, TKey extends keyof TDerived["FOREIGN_MODELS"]>(
        this: TDerived,
        field: TKey,
        dependencies?: React.DependencyList
    ) {
        type TModelName = TDerived["FOREIGN_MODELS"][TKey];
        type TForeignModel = TModelName extends keyof IModelMap ? InstanceType<IModelMap[TModelName]["Model"]> : never;
        const modelName = this.#getConstructor().FOREIGN_MODELS[field as string];
        const fieldValue = useForeignModelOne<TForeignModel>(this as any, modelName, dependencies);

        return fieldValue as TForeignModel;
    }

    protected getValue<TKey extends keyof TModel>(field: TKey): TModel[TKey] {
        return this.#store.getState()[field];
    }

    protected getForeignValue<TDerived extends BaseModel<TModel>, TKey extends keyof TDerived["FOREIGN_MODELS"]>(this: TDerived, field: TKey) {
        type TModelName = TDerived["FOREIGN_MODELS"][TKey];
        type TForeignModel = TModelName extends keyof IModelMap ? InstanceType<IModelMap[TModelName]["Model"]> : never;
        const modelName = this.#getConstructor().FOREIGN_MODELS[field as string];
        const fieldValue = getForeignModelArray<TForeignModel>(this as any, modelName);

        return fieldValue as TForeignModel[];
    }

    protected update<TUpdateModel extends Partial<TModel | TPickedModel<keyof IModelMap>>>(model: TUpdateModel) {
        syncForeignModelEdges({
            source: this as any,
            model: model as Record<string, any>,
            foreignModels: this.#getConstructor().FOREIGN_MODELS,
            isModelInstance: (value): value is TPickedModel<keyof IModelMap> => value instanceof BaseModel,
        });
        model = this.#getConstructor().convertModel(model);

        this.#store.setState(
            produce((draft: any) => {
                Object.keys(model).forEach((field) => {
                    const value = model[field as keyof TUpdateModel];
                    if (Utils.Type.isArray(value)) {
                        if (!draft[field]) {
                            draft[field] = [];
                        }
                        draft[field].splice(0, draft[field].length, ...(value as any[]));
                    } else {
                        draft[field] = value;
                    }
                });
            })
        );
    }

    protected subscribeSocketEvents<TProps>(events: TModelSocketHandlerFactory<any>[], props: TProps) {
        return subscribeModelSocketEvents({
            modelName: this.#getConstructor().MODEL_NAME,
            uid: this.uid,
            events,
            props,
        });
    }

    #getConstructor(): typeof BaseModel<TModel> {
        return this.constructor as typeof BaseModel<TModel>;
    }
}

export const cleanModels = () => {
    Object.values(ModelRegistry).forEach((registry) => registry.Model.cleanUp());
};
