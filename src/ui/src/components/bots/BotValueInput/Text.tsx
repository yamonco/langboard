import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Floating from "@/components/base/Floating";
import IconComponent from "@/components/base/IconComponent";
import Collaborative from "@/components/Collaborative";
import { TSharedBotValueInputProps } from "@/components/bots/BotValueInput/types";
import { useId } from "react";

function BotValueTextInput({
    collaborationType,
    uid,
    section,
    value,
    label,
    newValueRef,
    disabled,
    change,
    required,
    ref,
}: TSharedBotValueInputProps) {
    const [t] = useTranslation();
    const inputID = useId();

    const handleKeyEvent = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            e.preventDefault();
            e.stopPropagation();
            change?.();
            return;
        }
    };

    return (
        <Flex items="center" gap="1">
            <Collaborative.Input
                id={inputID}
                className="peer"
                collaborationType={collaborationType}
                uid={uid}
                section={section}
                field="value"
                placeholder=" "
                autoComplete="off"
                defaultValue={value}
                onKeyDown={handleKeyEvent}
                onValueChange={(value) => {
                    newValueRef.current = value;
                }}
                required={required}
                disabled={disabled}
                ref={ref as React.RefObject<HTMLInputElement>}
            >
                <Floating.Label className="select-none" htmlFor={inputID} required={required}>
                    {label}
                </Floating.Label>
            </Collaborative.Input>
            {change && (
                <Button type="button" size="icon-sm" variant="ghost" onClick={change} disabled={disabled} title={t("common.Save")}>
                    <IconComponent icon="check" size="4" />
                </Button>
            )}
        </Flex>
    );
}

export default BotValueTextInput;
