import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Label from "@/components/base/Label";
import Select from "@/components/base/Select";
import Collaborative from "@/components/Collaborative";
import CollaborativeControlOverlay from "@/components/Collaborative/ControlOverlay";
import { useCollaborativeText } from "@/components/Collaborative";
import { useBotValueDefaultInput } from "@/components/bots/BotValueInput/DefaultProvider";
import { API_URL } from "@/constants";
import { api } from "@/core/helpers/Api";
import { TAgentFormInput, IStringAgentFormInput, ISelectAgentFormInput, IIntegerAgentFormInput } from "@langboard/core/ai";
import { Utils } from "@langboard/core/utils";
import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

interface ISelectInputMeta {
    field: string;
    updatedAt: number;
    value: string;
}

interface IRemoteSelectInputMetaState {
    actorName: string;
    borderColor: string;
    updatedAt: number;
}

export interface IDefaultTypedInputProps {
    input: TAgentFormInput;
    disabled?: bool;
}

function DefaultTypedInput({ input, disabled }: IDefaultTypedInputProps) {
    const { selectedProvider } = useBotValueDefaultInput();
    switch (input.type) {
        case "text":
        case "password":
            return <DefaultStringInput key={`default-bot-json-input-${selectedProvider}-${input.name}`} input={input} disabled={disabled} />;
        case "select":
            return <DefaultSelectInput key={`default-bot-json-input-${selectedProvider}-${input.name}`} input={input} disabled={disabled} />;
        case "integer":
            return <DefaultIntegerInput key={`default-bot-json-input-${selectedProvider}-${input.name}`} input={input} disabled={disabled} />;
    }
}

function DefaultStringInput({ input, disabled }: { input: IStringAgentFormInput; disabled?: bool }) {
    const [t] = useTranslation();
    const { selectedProvider, valuesRef, setInputRef, setValue, isValidating, required, collaborationType, uid, section } = useBotValueDefaultInput();
    const inputID = useId();
    const collaborationField = `${selectedProvider}:${input.name}`;
    const [isDefault, setIsDefault] = useState(!!input.checkDefault && valuesRef.current[input.name] === input.checkDefault);
    const defaultValue = valuesRef.current[input.name] ?? input.defaultValue ?? "";

    useEffect(() => {
        if (Utils.Type.isNullOrUndefined(valuesRef.current[input.name]) && !Utils.Type.isNullOrUndefined(input.defaultValue)) {
            setValue(input.name)(input.defaultValue);
        }
    }, [input.defaultValue, input.name, setValue]);

    const inputComp = (
        <Collaborative.Input
            id={inputID}
            className="peer"
            type={input.type}
            collaborationType={collaborationType}
            uid={uid}
            section={section}
            field={collaborationField}
            name={input.name}
            placeholder=" "
            autoComplete="off"
            defaultValue={defaultValue}
            onValueChange={setValue(input.name)}
            required={required && !input.nullable}
            disabled={isValidating || isDefault || disabled}
            ref={setInputRef(input.name)}
        >
            <Floating.Label className="select-none" htmlFor={inputID} required={required && !input.nullable}>
                {input.label}
            </Floating.Label>
        </Collaborative.Input>
    );

    if (!Utils.Type.isString(input.checkDefault)) {
        return inputComp;
    }

    return (
        <Flex items="center" justify="between" gap="2">
            {inputComp}
            <Label display="flex" items="center" gap="1.5" w="36" cursor="pointer">
                <Checkbox
                    checked={isDefault}
                    onCheckedChange={(checked) => {
                        if (Utils.Type.isString(checked)) {
                            return;
                        }

                        setIsDefault(checked);
                        setValue(input.name)(checked ? input.checkDefault : "");
                    }}
                />
                {t("common.Use default")}
            </Label>
        </Flex>
    );
}

function DefaultSelectInput({ input, disabled }: { input: ISelectAgentFormInput; disabled?: bool }) {
    const [t] = useTranslation();
    const { selectedProvider, valuesRef, setInputRef, setValue, isValidating, required, collaborationType, uid, section } = useBotValueDefaultInput();
    const getInitialValue = useCallback(() => valuesRef.current[input.name] ?? input.defaultValue ?? input.options[0], [input]);
    const collaborationField = `${selectedProvider}:${input.name}`;
    const [currentValue, setCurrentValue] = useState(getInitialValue);
    const [options, setOptions] = useState<string[]>(input.options);
    const { remoteMeta, updateMeta, updateValue } = useCollaborativeText({
        collaborationType,
        uid,
        section,
        field: collaborationField,
        defaultValue: currentValue,
        disabled,
        onValueChange: (value) => {
            if (!value) {
                return;
            }

            valuesRef.current[input.name] = value;
            setValue(input.name)(value);
            setCurrentValue(value);
        },
    });
    const remoteSelectMeta = remoteMeta.reduce<IRemoteSelectInputMetaState | null>((acc, meta) => {
        const value = meta.value;
        if (
            !value ||
            !Utils.Type.isObject(value) ||
            !Utils.Type.isString((value as Record<string, unknown>).field) ||
            !Utils.Type.isString((value as Record<string, unknown>).value) ||
            !Utils.Type.isNumber((value as Record<string, unknown>).updatedAt)
        ) {
            return acc;
        }

        const parsedValue = value as ISelectInputMeta;
        if (parsedValue.field !== collaborationField) {
            return acc;
        }

        if (!acc || acc.updatedAt < parsedValue.updatedAt) {
            return {
                actorName: meta.name,
                borderColor: meta.color,
                updatedAt: parsedValue.updatedAt,
            };
        }

        return acc;
    }, null);
    const changeCurrentValue = useCallback(
        (value: string) => {
            setCurrentValue(value);
            setValue(input.name)(value);
            updateMeta({
                field: collaborationField,
                updatedAt: Date.now(),
                value,
            } satisfies ISelectInputMeta);
            updateValue(value);
        },
        [collaborationField, input.name, setValue, updateMeta, updateValue]
    );
    const fetchOptions = useCallback(async () => {
        if (!input.getOptions) {
            return;
        }

        const newOptions = await input.getOptions({ values: valuesRef.current, envs: { API_URL }, api });
        setOptions(() => newOptions);
        input.options = newOptions;
        if (!newOptions.includes(currentValue)) {
            changeCurrentValue(newOptions[0]);
        }
    }, [changeCurrentValue, currentValue, input]);

    useEffect(() => {
        if (!input.options.length) {
            fetchOptions();
        } else {
            setOptions(input.options);
        }
        setValue(input.name)(currentValue);
    }, [currentValue, fetchOptions, input.options, input.name, setValue]);

    useEffect(() => {
        if (!input.options.length) {
            fetchOptions();
        } else {
            setOptions(input.options);
        }
        const newValue = getInitialValue();
        setValue(input.name)(newValue);
        setCurrentValue(newValue);
    }, [getInitialValue, input.options, selectedProvider, setValue, fetchOptions]);

    const inputComp = (
        <div className="relative">
            {remoteSelectMeta ? (
                <CollaborativeControlOverlay
                    color={remoteSelectMeta.borderColor}
                    labelClassName="absolute right-2 z-[9999] max-w-32 truncate"
                    labelStyle={{ top: "-0.75rem" }}
                    name={remoteSelectMeta.actorName}
                />
            ) : null}
            <Floating.LabelSelect
                label={input.label}
                value={currentValue}
                onValueChange={changeCurrentValue}
                required={required && !input.nullable}
                disabled={isValidating || disabled}
                options={options.map((option) => (
                    <Select.Item value={option} key={`default-bot-json-input-${selectedProvider}-${input.name}-${option}`}>
                        {option}
                    </Select.Item>
                ))}
                ref={setInputRef(input.name)}
            />
        </div>
    );

    if (!input.getOptions) {
        return inputComp;
    }

    return (
        <Flex items="center" justify="between" gap="2">
            {inputComp}
            <Button
                type="button"
                size="icon"
                variant="outline"
                className="size-10"
                disabled={isValidating || disabled}
                onClick={fetchOptions}
                title={t("common.Refresh")}
            >
                <IconComponent icon="rotate-ccw" size="4" />
            </Button>
        </Flex>
    );
}

function DefaultIntegerInput({ input, disabled }: { input: IIntegerAgentFormInput; disabled?: bool }) {
    const { selectedProvider, valuesRef, setValue, required, isValidating, setInputRef, collaborationType, uid, section } = useBotValueDefaultInput();
    const inputID = useId();
    const collaborationField = `${selectedProvider}:${input.name}`;
    const defaultValue = valuesRef.current[input.name] ?? input.defaultValue ?? input.min;

    useEffect(() => {
        if (Utils.Type.isNullOrUndefined(valuesRef.current[input.name])) {
            setValue(input.name)(defaultValue);
        }
    }, [defaultValue, input.name, setValue]);

    return (
        <Collaborative.Input
            id={inputID}
            className="peer"
            type="number"
            collaborationType={collaborationType}
            uid={uid}
            section={section}
            field={collaborationField}
            name={input.name}
            placeholder=" "
            autoComplete="off"
            defaultValue={defaultValue}
            onValueChange={setValue(input.name)}
            required={required && !input.nullable}
            disabled={isValidating || disabled}
            min={input.min}
            max={input.max}
            ref={setInputRef(input.name)}
        >
            <Floating.Label className="select-none" htmlFor={inputID} required={required && !input.nullable}>
                {input.label}
            </Floating.Label>
        </Collaborative.Input>
    );
}

export default DefaultTypedInput;
