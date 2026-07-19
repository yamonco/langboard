/* eslint-disable @typescript-eslint/no-explicit-any */
import { TSharedBotValueInputProps } from "@/components/bots/BotValueInput/types";
import { showableDefaultInputs } from "@/components/bots/BotValueInput/utils";
import { API_URL, IS_OLLAMA_RUNNING } from "@/constants";
import { Agent, EBotPlatform, EBotPlatformRunningType, TAgentFormInput, TAgentModelName } from "@langboard/core/ai";
import { Utils } from "@langboard/core/utils";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IBotValueDefaultInputContext {
    collaborationType?: TSharedBotValueInputProps["collaborationType"];
    currentUser: TSharedBotValueInputProps["currentUser"];
    platform: EBotPlatform;
    platformRunningType: EBotPlatformRunningType;
    section?: TSharedBotValueInputProps["section"];
    uid?: TSharedBotValueInputProps["uid"];
    valuesRef: React.RefObject<Record<string, any>>;
    selectedProvider: TAgentModelName;
    setSelectedProvider: React.Dispatch<React.SetStateAction<TAgentModelName>>;
    selectedApis: string[];
    setSelectedApis: React.Dispatch<React.SetStateAction<string[]>>;
    selectedComfortTools: string[];
    setSelectedComfortTools: React.Dispatch<React.SetStateAction<string[]>>;
    comfortToolDescriptions: Record<string, string>;
    setComfortToolDescriptions: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    inputs: TAgentFormInput[];
    setInputs: React.Dispatch<React.SetStateAction<TAgentFormInput[]>>;
    errors: Record<string, string>;
    setErrors: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    apiList: Record<string, string>;
    setApiList: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    setValue: (name: string) => (value: any) => void;
    setInputRef: (name: string) => (element: HTMLElement | null) => void;
    required?: bool;
    isValidating: bool;
    showableInputs: ("api_names" | "provider" | "prompt")[];
    resetTick: number;
}

interface IBotValueDefaultInputProviderProps extends TSharedBotValueInputProps {
    children: React.ReactNode;
}

const initialContext = {
    currentUser: {} as TSharedBotValueInputProps["currentUser"],
    platform: EBotPlatform.Default,
    platformRunningType: EBotPlatformRunningType.Default,
    valuesRef: { current: {} },
    selectedProvider: "OpenAI" as TAgentModelName,
    setSelectedProvider: () => {},
    selectedApis: [] as string[],
    setSelectedApis: () => {},
    selectedComfortTools: [] as string[],
    setSelectedComfortTools: () => {},
    comfortToolDescriptions: {} as Record<string, string>,
    setComfortToolDescriptions: () => {},
    inputs: [] as TAgentFormInput[],
    setInputs: () => {},
    errors: {} as Record<string, string>,
    setErrors: () => {},
    apiList: {} as Record<string, string>,
    setApiList: () => {},
    setValue: () => () => {},
    setInputRef: () => () => {},
    required: false,
    isValidating: false,
    showableInputs: [],
    resetTick: 0,
};

const BotValueDefaultInputContext = createContext<IBotValueDefaultInputContext>(initialContext);

export const BotValueDefaultInputProvider = ({
    collaborationType,
    currentUser,
    disabled,
    platform,
    platformRunningType,
    section,
    uid,
    value,
    newValueRef,
    isValidating,
    required,
    ref,
    children,
}: IBotValueDefaultInputProviderProps): React.ReactNode => {
    const [t] = useTranslation();
    const valuesRef = useRef<Record<string, any>>(Utils.String.isJsonString(value) ? JSON.parse(value) : {});
    const [selectedProvider, setSelectedProvider] = useState<TAgentModelName>((valuesRef.current["agent_llm"] as TAgentModelName) ?? "OpenAI");
    const [selectedApis, setSelectedApis] = useState<string[]>((valuesRef.current["api_names"] as string[]) ?? []);
    const [selectedComfortTools, setSelectedComfortTools] = useState<string[]>((valuesRef.current["comfort_tool_names"] as string[]) ?? []);
    const [comfortToolDescriptions, setComfortToolDescriptions] = useState<Record<string, string>>(
        (valuesRef.current["comfort_tool_descriptions"] as Record<string, string>) ?? {}
    );
    const [inputs, setInputs] = useState<TAgentFormInput[]>([]);
    const inputsRef = useRef<Record<string, HTMLElement | null>>({});
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [resetTick, setResetTick] = useState(0);
    const syncValue = useCallback(() => {
        newValueRef.current = JSON.stringify(valuesRef.current);
    }, []);
    const setInputRef = (name: string) => (element: HTMLElement | null) => {
        inputsRef.current[name] = element;
    };
    const setValue = useCallback(
        (name: string) => (value: any) => {
            valuesRef.current[name] = value;
            syncValue();
        },
        [syncValue]
    );
    const createSafePatchValue = (patch: Record<string, unknown>) => {
        const allowedKeys = new Set([
            ...inputs.map((input) => input.name),
            "agent_llm",
            "api_names",
            "comfort_tool_names",
            "comfort_tool_descriptions",
            "comfort_tool_definitions",
            "system_prompt",
        ]);
        const blockedKeys = new Set(["api_key", "app_api_token", "token", "secret", "password"]);

        return Object.fromEntries(Object.entries(patch).filter(([key]) => allowedKeys.has(key) && !blockedKeys.has(key)));
    };
    const [apiList, setApiList] = useState<Record<string, string>>({});
    const showableInputs = useMemo(() => {
        return showableDefaultInputs[platform]?.[platformRunningType] ?? [];
    }, [platform, platformRunningType]);

    useEffect(() => {
        if (!disabled) {
            return;
        }

        const nextValues = Utils.String.isJsonString(value) ? JSON.parse(value) : {};
        valuesRef.current = nextValues;
        newValueRef.current = value;
        setSelectedProvider((nextValues["agent_llm"] as TAgentModelName) ?? "OpenAI");
        setSelectedApis((nextValues["api_names"] as string[]) ?? []);
        setSelectedComfortTools((nextValues["comfort_tool_names"] as string[]) ?? []);
        setComfortToolDescriptions((nextValues["comfort_tool_descriptions"] as Record<string, string>) ?? {});
        setErrors({});
        setResetTick((tick) => tick + 1);
    }, [disabled, value]);

    const getRef = () => ({
        type: "default-bot-json" as const,
        value: newValueRef.current,
        syncValue,
        validate: (shouldFocus?: bool) => {
            if (!required) {
                return true;
            }

            let focusable: HTMLElement | null = null;
            const newErrors: Record<string, string> = {};

            if (showableInputs.includes("provider")) {
                if (!valuesRef.current["agent_llm"]) {
                    newErrors["agent_llm"] = t("bot.agent.errors.missing.agent_llm");
                    if (!focusable) {
                        focusable = inputsRef.current.agent_llm;
                    }
                }
            }

            inputs.forEach((input) => {
                const value = valuesRef.current[input.name];
                if (!value && !input.nullable) {
                    newErrors[input.name] = t(`bot.agent.errors.missing.${input.name}`);
                    if (!focusable) {
                        focusable = inputsRef.current[input.name];
                    }
                }
            });

            if (focusable) {
                setErrors(() => newErrors);
                if (shouldFocus) {
                    focusable?.focus();
                }
                return false;
            }

            return true;
        },
        onSuccess: () => {
            setErrors(() => ({}));
        },
        patchValue: (patch: Record<string, unknown>) => {
            const safePatch = createSafePatchValue(patch);
            valuesRef.current = {
                ...valuesRef.current,
                ...safePatch,
            };
            syncValue();

            if (Utils.Type.isString(safePatch["agent_llm"])) {
                setSelectedProvider(safePatch["agent_llm"] as TAgentModelName);
            }

            if (Utils.Type.isArray(safePatch["api_names"]) && safePatch["api_names"].every((apiName) => Utils.Type.isString(apiName))) {
                setSelectedApis(safePatch["api_names"] as string[]);
            }

            if (
                Utils.Type.isArray(safePatch["comfort_tool_names"]) &&
                safePatch["comfort_tool_names"].every((comfortToolName) => Utils.Type.isString(comfortToolName))
            ) {
                setSelectedComfortTools(safePatch["comfort_tool_names"] as string[]);
            }

            if (Utils.Type.isObject(safePatch["comfort_tool_descriptions"])) {
                setComfortToolDescriptions(safePatch["comfort_tool_descriptions"] as Record<string, string>);
            }

            setResetTick((tick) => tick + 1);
        },
    });

    if (Utils.Type.isFunction(ref)) {
        ref(getRef());
    } else if (ref) {
        ref.current = getRef();
    }

    useEffect(() => {
        for (let i = 0; i < inputs.length; ++i) {
            const input = inputs[i];

            if (input.type === "select") {
                delete valuesRef.current[input.name];
            }
        }

        if (showableInputs.includes("provider")) {
            setValue("agent_llm")(selectedProvider);
        } else {
            delete valuesRef.current["agent_llm"];
            syncValue();
        }

        setInputs(
            Agent.getInputForm({
                platform,
                platformRunningType,
                model: selectedProvider,
                envs: { IS_OLLAMA_RUNNING, API_URL },
            })
        );
    }, [platform, platformRunningType, selectedProvider, setValue, showableInputs, syncValue]);

    return (
        <BotValueDefaultInputContext.Provider
            value={{
                collaborationType,
                currentUser,
                platform,
                platformRunningType,
                section,
                uid,
                valuesRef,
                selectedProvider,
                setSelectedProvider,
                selectedApis,
                setSelectedApis,
                selectedComfortTools,
                setSelectedComfortTools,
                comfortToolDescriptions,
                setComfortToolDescriptions,
                inputs,
                setInputs,
                errors,
                setErrors,
                apiList,
                setApiList,
                setValue,
                setInputRef,
                required,
                isValidating,
                showableInputs,
                resetTick,
            }}
        >
            {children}
        </BotValueDefaultInputContext.Provider>
    );
};

export const useBotValueDefaultInput = () => {
    const context = useContext(BotValueDefaultInputContext);
    if (!context) {
        throw new Error("useBotValueDefaultInput must be used within an BotValueDefaultInputProvider");
    }
    return context;
};
