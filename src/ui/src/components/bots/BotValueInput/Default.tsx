import { useEffect, useMemo, useState } from "react";
import { AGENT_MODELS, TAgentModelName } from "@langboard/core/ai";
import Box from "@/components/base/Box";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Select from "@/components/base/Select";
import SubmitButton from "@/components/base/SubmitButton";
import Tooltip from "@/components/base/Tooltip";
import Button from "@/components/base/Button";
import Badge from "@/components/base/Badge";
import { useTranslation } from "react-i18next";
import FormErrorMessage from "@/components/FormErrorMessage";
import { TSharedBotValueInputProps } from "@/components/bots/BotValueInput/types";
import useGetApiList from "@/controllers/api/settings/schemas/useGetApiList";
import useGetApiComfortToolList from "@/controllers/api/settings/schemas/useGetApiComfortToolList";
import MultiSelect from "@/components/MultiSelect";
import Collaborative from "@/components/Collaborative";
import CollaborativeControlOverlay from "@/components/Collaborative/ControlOverlay";
import CollaborativeUserLabel from "@/components/Collaborative/UserLabel";
import { useCollaborativeText } from "@/components/Collaborative";
import { BotValueDefaultInputProvider, useBotValueDefaultInput } from "@/components/bots/BotValueInput/DefaultProvider";
import DefaultTypedInput from "@/components/bots/BotValueInput/DefaultTypedInput";
import { providerIconMap } from "@/components/bots/BotValueInput/utils";
import { ApiComfortToolModel } from "@/core/models";
import { Utils } from "@langboard/core/utils";
import BotPromptEditor from "@/components/bots/BotValueInput/BotPromptEditor";
import BotActionSuggestionPanel from "@/components/bots/BotValueInput/BotActionSuggestionPanel";
import type { IBotActionSuggestion } from "@/controllers/api/settings/bots/useSuggestBotActions";

interface IApiSelectionMeta {
    added: bool;
    apiName: string;
    updatedAt: number;
}

interface IRemoteApiMetaState {
    actorName: string;
    added: bool;
    borderColor: string;
    updatedAt: number;
}

interface IProviderSelectionMeta {
    provider: TAgentModelName;
    updatedAt: number;
}

interface IRemoteProviderMetaState {
    actorName: string;
    borderColor: string;
    provider: TAgentModelName;
    updatedAt: number;
}

interface IComfortToolSelectionMeta {
    added: bool;
    comfortToolName: string;
    updatedAt: number;
}

function BotValueDefaultInput(props: TSharedBotValueInputProps) {
    return (
        <BotValueDefaultInputProvider {...props}>
            <BotValueDefaultInputDisplay {...props} />
        </BotValueDefaultInputProvider>
    );
}

function BotValueDefaultInputDisplay({
    isValidating,
    disabled,
    required,
    change,
    isEditing,
    startEditing,
    cancelEditing,
    initialActionSuggestions,
}: TSharedBotValueInputProps) {
    const [t] = useTranslation();
    const { mutateAsync: getApiListMutateAsync } = useGetApiList({ interceptToast: true });
    const { mutateAsync: getApiComfortToolListMutateAsync } = useGetApiComfortToolList({ interceptToast: true });
    const {
        valuesRef,
        setInputRef,
        selectedProvider,
        setSelectedProvider,
        setValue,
        inputs,
        errors,
        selectedApis,
        setSelectedApis,
        selectedComfortTools,
        setSelectedComfortTools,
        comfortToolDescriptions,
        setComfortToolDescriptions,
        apiList,
        setApiList,
        showableInputs,
        collaborationType,
        currentUser,
        uid,
        section,
        resetTick,
    } = useBotValueDefaultInput();
    const [promptValue, setPromptValue] = useState<string>((valuesRef.current["system_prompt"] as string) ?? "");
    const [promptEditorResetKey, setPromptEditorResetKey] = useState(0);
    const comfortToolList = ApiComfortToolModel.Model.useModels(() => true);
    const providerCollaboration = useCollaborativeText({
        collaborationType,
        uid,
        section,
        field: "agent_llm",
        defaultValue: selectedProvider,
        disabled: disabled || !showableInputs.includes("provider"),
        onValueChange: (value) => {
            if (!AGENT_MODELS.includes(value as TAgentModelName)) {
                return;
            }

            const nextProvider = value as TAgentModelName;
            setSelectedProvider(nextProvider);
            setValue("agent_llm")(nextProvider);
        },
    });
    const apiNamesCollaboration = useCollaborativeText({
        collaborationType,
        uid,
        section,
        field: "api_names",
        defaultValue: JSON.stringify(selectedApis),
        disabled: disabled || !showableInputs.includes("api_names"),
        onValueChange: (value) => {
            if (!Utils.String.isJsonString(value)) {
                return;
            }

            const nextApis = JSON.parse(value);
            if (!Utils.Type.isArray(nextApis) || nextApis.some((apiName) => !Utils.Type.isString(apiName))) {
                return;
            }

            setSelectedApis(nextApis as string[]);
            setValue("api_names")(nextApis);
        },
    });
    const comfortToolNamesCollaboration = useCollaborativeText({
        collaborationType,
        uid,
        section,
        field: "comfort_tool_names",
        defaultValue: JSON.stringify(selectedComfortTools),
        disabled: disabled || !showableInputs.includes("api_names"),
        onValueChange: (value) => {
            if (!Utils.String.isJsonString(value)) {
                return;
            }

            const nextComfortTools = JSON.parse(value);
            if (!Utils.Type.isArray(nextComfortTools) || nextComfortTools.some((comfortToolName) => !Utils.Type.isString(comfortToolName))) {
                return;
            }

            setSelectedComfortTools(nextComfortTools as string[]);
            setValue("comfort_tool_names")(nextComfortTools);
        },
    });
    const remoteApiMetaMap = useMemo(() => {
        return apiNamesCollaboration.remoteMeta.reduce<Record<string, IRemoteApiMetaState>>((acc, meta) => {
            const value = meta.value;
            if (
                !value ||
                !Utils.Type.isObject(value) ||
                !Utils.Type.isString((value as Record<string, unknown>).apiName) ||
                !Utils.Type.isBool((value as Record<string, unknown>).added) ||
                !Utils.Type.isNumber((value as Record<string, unknown>).updatedAt)
            ) {
                return acc;
            }

            const parsedValue = value as IApiSelectionMeta;
            const previous = acc[parsedValue.apiName];
            if (!previous || previous.updatedAt < parsedValue.updatedAt) {
                acc[parsedValue.apiName] = {
                    actorName: meta.name,
                    added: parsedValue.added,
                    borderColor: meta.color,
                    updatedAt: parsedValue.updatedAt,
                };
            }

            return acc;
        }, {});
    }, [apiNamesCollaboration.remoteMeta]);
    const remoteProviderMeta = useMemo(() => {
        const nextRemoteProviderMeta = providerCollaboration.remoteMeta.reduce<IRemoteProviderMetaState | null>((acc, meta) => {
            const value = meta.value;
            if (
                !value ||
                !Utils.Type.isObject(value) ||
                !Utils.Type.isString((value as Record<string, unknown>).provider) ||
                !Utils.Type.isNumber((value as Record<string, unknown>).updatedAt)
            ) {
                return acc;
            }

            const parsedValue = value as IProviderSelectionMeta;
            if (parsedValue.provider !== selectedProvider) {
                return acc;
            }

            if (!acc || acc.updatedAt < parsedValue.updatedAt) {
                return {
                    actorName: meta.name,
                    borderColor: meta.color,
                    provider: parsedValue.provider,
                    updatedAt: parsedValue.updatedAt,
                };
            }

            return acc;
        }, null);

        return nextRemoteProviderMeta;
    }, [providerCollaboration.remoteMeta, selectedProvider]);
    const remoteComfortToolMetaMap = useMemo(() => {
        return comfortToolNamesCollaboration.remoteMeta.reduce<Record<string, IRemoteApiMetaState>>((acc, meta) => {
            const value = meta.value;
            if (
                !value ||
                !Utils.Type.isObject(value) ||
                !Utils.Type.isString((value as Record<string, unknown>).comfortToolName) ||
                !Utils.Type.isBool((value as Record<string, unknown>).added) ||
                !Utils.Type.isNumber((value as Record<string, unknown>).updatedAt)
            ) {
                return acc;
            }

            const parsedValue = value as IComfortToolSelectionMeta;
            const previous = acc[parsedValue.comfortToolName];
            if (!previous || previous.updatedAt < parsedValue.updatedAt) {
                acc[parsedValue.comfortToolName] = {
                    actorName: meta.name,
                    added: parsedValue.added,
                    borderColor: meta.color,
                    updatedAt: parsedValue.updatedAt,
                };
            }

            return acc;
        }, {});
    }, [comfortToolNamesCollaboration.remoteMeta]);

    const changeSelectedComfortTools = (nextComfortTools: string[]) => {
        const addedComfortToolName = nextComfortTools.find((comfortToolName) => !selectedComfortTools.includes(comfortToolName)) ?? "";
        const removedComfortToolName = selectedComfortTools.find((comfortToolName) => !nextComfortTools.includes(comfortToolName)) ?? "";
        const nextDefinitionMap = Object.fromEntries(
            nextComfortTools.map((comfortToolName) => [comfortToolName, comfortToolMap[comfortToolName]]).filter(([, comfortTool]) => !!comfortTool)
        );

        comfortToolNamesCollaboration.updateMeta(
            addedComfortToolName || removedComfortToolName
                ? ({
                      added: !!addedComfortToolName,
                      comfortToolName: addedComfortToolName || removedComfortToolName,
                      updatedAt: Date.now(),
                  } satisfies IComfortToolSelectionMeta)
                : null
        );
        const nextDescriptionMap = Object.fromEntries(
            Object.entries(comfortToolDescriptions).filter(([comfortToolName]) => nextComfortTools.includes(comfortToolName))
        );
        setSelectedComfortTools(nextComfortTools);
        setValue("comfort_tool_names")(nextComfortTools);
        setValue("comfort_tool_definitions")(nextDefinitionMap);
        setComfortToolDescriptions(nextDescriptionMap);
        setValue("comfort_tool_descriptions")(nextDescriptionMap);
        comfortToolNamesCollaboration.updateValue(JSON.stringify(nextComfortTools));
    };

    const changeComfortToolDescription = (comfortToolName: string) => (description: string) => {
        const nextDescriptions = { ...comfortToolDescriptions };
        if (description) {
            nextDescriptions[comfortToolName] = description;
        } else {
            delete nextDescriptions[comfortToolName];
        }

        setComfortToolDescriptions(nextDescriptions);
        setValue("comfort_tool_descriptions")(nextDescriptions);
    };

    const changeSelectedApis = (nextApis: string[]) => {
        const addedApiName = nextApis.find((apiName) => !selectedApis.includes(apiName)) ?? "";
        const removedApiName = selectedApis.find((apiName) => !nextApis.includes(apiName)) ?? "";

        apiNamesCollaboration.updateMeta(
            addedApiName || removedApiName
                ? ({
                      added: !!addedApiName,
                      apiName: addedApiName || removedApiName,
                      updatedAt: Date.now(),
                  } satisfies IApiSelectionMeta)
                : null
        );
        setSelectedApis(nextApis);
        setValue("api_names")(nextApis);
        apiNamesCollaboration.updateValue(JSON.stringify(nextApis));
    };

    const changeSelectedProvider = (nextProvider: TAgentModelName) => {
        const updatedAt = Date.now();
        providerCollaboration.updateMeta({
            provider: nextProvider,
            updatedAt,
        } satisfies IProviderSelectionMeta);
        setSelectedProvider(nextProvider);
        setValue("agent_llm")(nextProvider);
        providerCollaboration.updateValue(nextProvider);
    };

    const changePromptValue = (nextPrompt: string) => {
        setPromptValue(nextPrompt);
        setValue("system_prompt")(nextPrompt);
    };

    const applyActionSuggestion = (suggestion: IBotActionSuggestion) => {
        if (suggestion.source === "comfort_tool") {
            if (selectedComfortTools.includes(suggestion.name)) {
                return;
            }

            changeSelectedComfortTools([...selectedComfortTools, suggestion.name]);
            if (suggestion.description) {
                changeComfortToolDescription(suggestion.name)(suggestion.description);
            }
            return;
        }

        if (suggestion.source !== "api") {
            return;
        }

        if (selectedApis.includes(suggestion.name)) {
            return;
        }

        changeSelectedApis([...selectedApis, suggestion.name]);
    };

    const allApiNames = useMemo(() => Object.keys(apiList), [apiList]);
    const isAllApiSelected = !!allApiNames.length && allApiNames.every((apiName) => selectedApis.includes(apiName));
    const comfortToolMap = useMemo(
        () => Object.fromEntries([...comfortToolList].map((comfortTool) => [comfortTool.name, comfortTool])),
        [comfortToolList]
    );
    const allComfortToolNames = useMemo(() => [...comfortToolList].map((comfortTool) => comfortTool.name), [comfortToolList]);
    const isAllComfortToolSelected =
        !!allComfortToolNames.length && allComfortToolNames.every((comfortToolName) => selectedComfortTools.includes(comfortToolName));

    useEffect(() => {
        setValue("api_names")(selectedApis);
    }, [selectedApis, setValue]);

    useEffect(() => {
        setValue("comfort_tool_names")(selectedComfortTools);
        setValue("comfort_tool_definitions")(
            Object.fromEntries(
                selectedComfortTools
                    .map((comfortToolName) => [comfortToolName, comfortToolMap[comfortToolName]])
                    .filter(([, comfortTool]) => !!comfortTool)
            )
        );
    }, [comfortToolMap, selectedComfortTools, setValue]);

    useEffect(() => {
        const getApiLists = async () => {
            const apiList = await getApiListMutateAsync({});
            await getApiComfortToolListMutateAsync({});
            setApiList(apiList || {});
        };
        getApiLists();
    }, []);

    useEffect(() => {
        setPromptValue((valuesRef.current["system_prompt"] as string) ?? "");
        setPromptEditorResetKey((key) => key + 1);
    }, [disabled, resetTick]);

    return (
        <Box border rounded px="3" pt="5" pb="4" position="relative">
            <Box position="absolute" className="start-2 top-2.5 z-10 origin-[0] -translate-y-6 bg-background px-2">
                {t("bot.agent.Agent settings")}
            </Box>
            {showableInputs.includes("api_names") && (
                <Box>
                    <Box mb="4">
                        {isEditing ? (
                            <>
                                <Flex justify="between" items="center" gap="2" mb="1">
                                    <Box textSize="sm" className="font-medium">
                                        {t("bot.agent.Comfort tools")}
                                    </Box>
                                    <Flex gap="1">
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="h-7 px-2"
                                            disabled={isValidating || disabled || isAllComfortToolSelected}
                                            onClick={() => changeSelectedComfortTools(allComfortToolNames)}
                                        >
                                            {t("common.Select all")}
                                        </Button>
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="h-7 px-2"
                                            disabled={isValidating || disabled || !selectedComfortTools.length}
                                            onClick={() => changeSelectedComfortTools([])}
                                        >
                                            {t("common.Clear")}
                                        </Button>
                                    </Flex>
                                </Flex>
                                <MultiSelect
                                    placeholder={t("bot.agent.Select comfort tool(s) to use")}
                                    selections={allComfortToolNames.map((value) => ({ label: comfortToolMap[value].label || value, value }))}
                                    selectedValue={selectedComfortTools}
                                    listClassName="absolute w-[calc(100%_-_theme(spacing.6))]"
                                    badgeListClassName="max-h-28 overflow-y-auto relative"
                                    inputClassName="sticky bottom-0 bg-background ml-0 pl-2"
                                    onValueChange={changeSelectedComfortTools}
                                    createBadgeWrapper={(badge, value) => {
                                        const remoteComfortToolMeta = remoteComfortToolMetaMap[value];

                                        return (
                                            <span className="relative inline-flex">
                                                {remoteComfortToolMeta?.added ? (
                                                    <CollaborativeUserLabel
                                                        className="absolute left-1 top-0 z-[9999] -translate-y-1/2"
                                                        color={remoteComfortToolMeta.borderColor}
                                                        name={remoteComfortToolMeta.actorName}
                                                    />
                                                ) : null}
                                                <Tooltip.Root>
                                                    <Tooltip.Trigger asChild>
                                                        <span
                                                            className="inline-flex rounded-md border-2 border-transparent"
                                                            style={
                                                                remoteComfortToolMeta?.added
                                                                    ? { borderColor: remoteComfortToolMeta.borderColor }
                                                                    : undefined
                                                            }
                                                        >
                                                            {badge}
                                                        </span>
                                                    </Tooltip.Trigger>
                                                    <Tooltip.Content className="max-w-[min(95vw,theme(spacing.96))]">
                                                        <Box>{comfortToolMap[value]?.description}</Box>
                                                        <Box mt="1" textSize="xs" className="text-muted-foreground">
                                                            {comfortToolMap[value]?.api_names.join(", ")}
                                                        </Box>
                                                    </Tooltip.Content>
                                                </Tooltip.Root>
                                            </span>
                                        );
                                    }}
                                    renderSelectableItem={(item) => {
                                        const remoteComfortToolMeta = remoteComfortToolMetaMap[item.value];
                                        if (!remoteComfortToolMeta || remoteComfortToolMeta.added) {
                                            return item.label;
                                        }

                                        return (
                                            <div
                                                className="relative w-full rounded-md border-2 px-2 py-1"
                                                style={{ borderColor: remoteComfortToolMeta.borderColor }}
                                            >
                                                <CollaborativeUserLabel
                                                    className="absolute left-2 top-0 z-[9999] -translate-y-1/2"
                                                    color={remoteComfortToolMeta.borderColor}
                                                    name={remoteComfortToolMeta.actorName}
                                                />
                                                <span>{item.label}</span>
                                            </div>
                                        );
                                    }}
                                    disabled={isValidating || disabled}
                                />
                                {selectedComfortTools.length ? (
                                    <Flex direction="col" gap="2" mt="2">
                                        {selectedComfortTools.map((comfortToolName) => (
                                            <Collaborative.Textarea
                                                key={`default-bot-comfort-tool-description-${comfortToolName}`}
                                                collaborationType={collaborationType}
                                                uid={uid}
                                                section={section}
                                                field={`comfort_tool_description_${comfortToolName}`}
                                                defaultValue={comfortToolDescriptions[comfortToolName] ?? ""}
                                                placeholder={t("bot.agent.Add comfort tool description", {
                                                    tool: comfortToolMap[comfortToolName]?.label ?? comfortToolName,
                                                })}
                                                resize="none"
                                                className="min-h-16"
                                                disabled={isValidating || disabled}
                                                onValueChange={changeComfortToolDescription(comfortToolName)}
                                            />
                                        ))}
                                    </Flex>
                                ) : null}
                            </>
                        ) : (
                            <>
                                <Box textSize="sm" mb="1" className="font-medium">
                                    {t("bot.agent.Comfort tools")}
                                </Box>
                                <Flex wrap gap="1.5" className="min-h-9 rounded-md border border-input bg-muted/20 px-3 py-2">
                                    {selectedComfortTools.length ? (
                                        selectedComfortTools.map((comfortToolName) => (
                                            <Tooltip.Root key={`default-bot-comfort-tool-view-${comfortToolName}`}>
                                                <Tooltip.Trigger asChild>
                                                    <Badge variant="secondary" className="max-w-full">
                                                        <span className="truncate">{comfortToolMap[comfortToolName]?.label ?? comfortToolName}</span>
                                                    </Badge>
                                                </Tooltip.Trigger>
                                                <Tooltip.Content className="max-w-[min(95vw,theme(spacing.96))]">
                                                    <Box>{comfortToolMap[comfortToolName]?.description}</Box>
                                                    {comfortToolDescriptions[comfortToolName] ? (
                                                        <Box mt="1">{comfortToolDescriptions[comfortToolName]}</Box>
                                                    ) : null}
                                                </Tooltip.Content>
                                            </Tooltip.Root>
                                        ))
                                    ) : (
                                        <Box textSize="sm" className="text-muted-foreground">
                                            {t("bot.agent.Select comfort tool(s) to use")}
                                        </Box>
                                    )}
                                </Flex>
                            </>
                        )}
                    </Box>
                    <Box textSize="sm" mb="1" className="font-medium">
                        {t("bot.agent.Base tools")}
                    </Box>
                    {isEditing ? (
                        <>
                            <Flex justify="end" gap="1" mb="1">
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2"
                                    disabled={isValidating || disabled || isAllApiSelected}
                                    onClick={() => changeSelectedApis(allApiNames)}
                                >
                                    {t("common.Select all")}
                                </Button>
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="h-7 px-2"
                                    disabled={isValidating || disabled || !selectedApis.length}
                                    onClick={() => changeSelectedApis([])}
                                >
                                    {t("common.Clear")}
                                </Button>
                            </Flex>
                            <MultiSelect
                                placeholder={t("bot.agent.Select API(s) to use")}
                                selections={allApiNames.map((value) => ({ label: value, value }))}
                                selectedValue={selectedApis}
                                listClassName="absolute w-[calc(100%_-_theme(spacing.6))]"
                                badgeListClassName="max-h-28 overflow-y-auto relative"
                                inputClassName="sticky bottom-0 bg-background ml-0 pl-2"
                                onValueChange={changeSelectedApis}
                                createBadgeWrapper={(badge, value) => {
                                    const remoteApiMeta = remoteApiMetaMap[value];

                                    return (
                                        <span className="relative inline-flex">
                                            {remoteApiMeta?.added ? (
                                                <CollaborativeUserLabel
                                                    className="absolute left-1 top-0 z-[9999] -translate-y-1/2"
                                                    color={remoteApiMeta.borderColor}
                                                    name={remoteApiMeta.actorName}
                                                />
                                            ) : null}
                                            <Tooltip.Root>
                                                <Tooltip.Trigger asChild>
                                                    <span
                                                        className="inline-flex rounded-md border-2 border-transparent"
                                                        style={remoteApiMeta?.added ? { borderColor: remoteApiMeta.borderColor } : undefined}
                                                    >
                                                        {badge}
                                                    </span>
                                                </Tooltip.Trigger>
                                                <Tooltip.Content className="max-w-[min(95vw,theme(spacing.96))]">{apiList[value]}</Tooltip.Content>
                                            </Tooltip.Root>
                                        </span>
                                    );
                                }}
                                renderSelectableItem={(item) => {
                                    const remoteApiMeta = remoteApiMetaMap[item.value];
                                    if (!remoteApiMeta || remoteApiMeta.added) {
                                        return item.label;
                                    }

                                    return (
                                        <div
                                            className="relative w-full rounded-md border-2 px-2 py-1"
                                            style={{ borderColor: remoteApiMeta.borderColor }}
                                        >
                                            <CollaborativeUserLabel
                                                className="absolute left-2 top-0 z-[9999] -translate-y-1/2"
                                                color={remoteApiMeta.borderColor}
                                                name={remoteApiMeta.actorName}
                                            />
                                            <span>{item.label}</span>
                                        </div>
                                    );
                                }}
                                disabled={isValidating || disabled}
                            />
                        </>
                    ) : (
                        <Flex wrap gap="1.5" className="min-h-9 rounded-md border border-input bg-muted/20 px-3 py-2">
                            {selectedApis.length ? (
                                selectedApis.map((apiName) => (
                                    <Tooltip.Root key={`default-bot-api-view-${apiName}`}>
                                        <Tooltip.Trigger asChild>
                                            <Badge variant="secondary" className="max-w-full">
                                                <span className="truncate">{apiName}</span>
                                            </Badge>
                                        </Tooltip.Trigger>
                                        <Tooltip.Content className="max-w-[min(95vw,theme(spacing.96))]">{apiList[apiName]}</Tooltip.Content>
                                    </Tooltip.Root>
                                ))
                            ) : (
                                <Box textSize="sm" className="text-muted-foreground">
                                    {t("bot.agent.Select API(s) to use")}
                                </Box>
                            )}
                        </Flex>
                    )}
                </Box>
            )}
            {showableInputs.includes("provider") && (
                <Box mt="4" position="relative">
                    {remoteProviderMeta ? (
                        <CollaborativeControlOverlay
                            color={remoteProviderMeta.borderColor}
                            labelClassName="absolute right-2 z-[9999] max-w-32 truncate"
                            labelStyle={{ top: "-0.75rem" }}
                            name={remoteProviderMeta.actorName}
                        />
                    ) : null}
                    <Floating.LabelSelect
                        label={t("bot.agent.Select a provider")}
                        value={selectedProvider}
                        onValueChange={changeSelectedProvider as (value: string) => void}
                        required={required}
                        disabled={isValidating || disabled}
                        options={AGENT_MODELS.map((option) => (
                            <Select.Item key={`default-bot-json-input-agent-${option}`} value={option}>
                                <Flex items="center" gap="2">
                                    <IconComponent icon={providerIconMap[option]} size="4" />
                                    {option}
                                </Flex>
                            </Select.Item>
                        ))}
                        ref={setInputRef("agent_llm")}
                    />
                    {errors.agent_llm && <FormErrorMessage error={errors.agent_llm} notInForm />}
                </Box>
            )}
            {showableInputs.includes("prompt") && (
                <Box mt="4">
                    <BotPromptEditor
                        currentUser={currentUser}
                        value={promptValue}
                        disabled={isValidating || disabled}
                        isValidating={isValidating}
                        resetKey={promptEditorResetKey}
                        onValueChange={changePromptValue}
                        inputRef={setInputRef("system_prompt")}
                    />
                    {showableInputs.includes("api_names") && !disabled ? (
                        <BotActionSuggestionPanel
                            prompt={promptValue}
                            selectedApis={selectedApis}
                            selectedComfortTools={selectedComfortTools}
                            initialSuggestions={initialActionSuggestions}
                            disabled={isValidating || disabled}
                            onApplySuggestion={applyActionSuggestion}
                        />
                    ) : null}
                </Box>
            )}
            {inputs.map((input) => (
                <Box mt="4" key={`default-bot-json-input-${selectedProvider}-${input.name}`}>
                    <DefaultTypedInput input={input} disabled={disabled} />
                    {errors[input.name] && <FormErrorMessage error={errors[input.name]} notInForm />}
                </Box>
            ))}

            {change && (
                <Flex mt="4" justify="center" gap="1">
                    {isEditing ? (
                        <>
                            <Button type="button" variant="secondary" size="sm" onClick={cancelEditing} disabled={isValidating}>
                                {t("common.Cancel")}
                            </Button>
                            <SubmitButton type="button" size="sm" onClick={change} isValidating={isValidating} disabled={disabled}>
                                {t("common.Save")}
                            </SubmitButton>
                        </>
                    ) : (
                        <Button type="button" size="sm" onClick={startEditing} disabled={isValidating || !startEditing}>
                            {t("common.Edit")}
                        </Button>
                    )}
                </Flex>
            )}
        </Box>
    );
}

export default BotValueDefaultInput;
