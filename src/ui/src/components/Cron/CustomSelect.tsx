import { useCallback, useMemo, useRef } from "react";
import { formatValue, parsePartArray, partToString } from "@/components/Cron/converter";
import { Clicks, CustomSelectProps } from "@/components/Cron/types";
import { sort } from "@/components/Cron/utils";
import Select from "@/components/base/Select";
import MultiSelect from "@/components/MultiSelect";
import { useTranslation } from "react-i18next";

function CustomSelect(props: CustomSelectProps) {
    const [t] = useTranslation();
    const {
        placeholder,
        value,
        optionsList,
        setValue,
        humanizeLabels,
        disabled,
        readOnly,
        leadingZero,
        clockFormat,
        unit,
        periodicityOnDoubleClick,
        mode,
        filterOption = () => true,
    } = props;

    const stringValue = useMemo(() => {
        if (value && Array.isArray(value)) {
            return value.map((value: number) => value.toString());
        }
    }, [value]);

    const selectedLabels = useMemo(() => {
        const labels = value?.map((value: number) => formatValue(value, unit, humanizeLabels, leadingZero, clockFormat)) ?? [];
        if (labels.length && isNaN(Number(labels[0]))) {
            return labels.join(", ");
        }

        if (!value || value[0] !== Number(labels[0])) {
            return "";
        }

        const parsedArray = parsePartArray(value, unit);
        const cronValue = partToString(parsedArray, unit, humanizeLabels, leadingZero, clockFormat);
        const testEveryValue = cronValue.match(/^\*\/([0-9]+),?/) || [];

        return testEveryValue[1] ? t("cron.Every interval", { count: Number(testEveryValue[1]) }) : cronValue;
    }, [value, unit, humanizeLabels, leadingZero, clockFormat, t]);

    const options = useMemo(() => {
        if (optionsList) {
            return optionsList
                .map((option, index) => {
                    const number = unit.min === 0 ? index : index + 1;

                    return {
                        value: number.toString(),
                        label: option,
                    };
                })
                .filter(filterOption);
        }

        return [...Array(unit.total)]
            .map((_, index) => {
                const number = unit.min === 0 ? index : index + 1;

                return {
                    value: number.toString(),
                    label: formatValue(number, unit, humanizeLabels, leadingZero, clockFormat),
                };
            })
            .filter(filterOption);
    }, [optionsList, leadingZero, humanizeLabels, clockFormat]);

    const simpleClick = useCallback(
        (newValueOption: number | number[]) => {
            const newValueOptions = Array.isArray(newValueOption) ? sort(newValueOption) : [newValueOption];
            let newValue: number[] = newValueOptions;

            if (value) {
                newValue = mode === "single" ? [] : [...value];

                newValueOptions.forEach((o) => {
                    const newValueOptionNumber = Number(o);

                    if (value.some((v) => v === newValueOptionNumber)) {
                        newValue = newValue.filter((v) => v !== newValueOptionNumber);
                    } else {
                        newValue = sort([...newValue, newValueOptionNumber]);
                    }
                });
            }

            if (newValue.length === unit.total) {
                setValue([]);
            } else {
                setValue(newValue);
            }
        },
        [setValue, value]
    );

    const doubleClick = useCallback(
        (newValueOption: number) => {
            if (newValueOption !== 0 && newValueOption !== 1) {
                const limit = unit.total + unit.min;
                const newValue: number[] = [];

                for (let i = unit.min; i < limit; i++) {
                    if (i % newValueOption === 0) {
                        newValue.push(i);
                    }
                }
                const oldValueEqualNewValue =
                    value && newValue && value.length === newValue.length && value.every((v: number, i: number) => v === newValue[i]);
                const allValuesSelected = newValue.length === options.length;

                if (allValuesSelected) {
                    setValue([]);
                } else if (oldValueEqualNewValue) {
                    setValue([]);
                } else {
                    setValue(newValue);
                }
            } else {
                setValue([]);
            }
        },
        [value, options, setValue]
    );

    const clicksRef = useRef<Clicks[]>([]);
    const onOptionClick = useCallback(
        (newValueOption: string) => {
            if (!readOnly) {
                const doubleClickTimeout = 300;
                const clicks = clicksRef.current;

                clicks.push({
                    time: new Date().getTime(),
                    value: Number(newValueOption),
                });

                const id = window.setTimeout(() => {
                    if (
                        periodicityOnDoubleClick &&
                        clicks.length > 1 &&
                        clicks[clicks.length - 1].time - clicks[clicks.length - 2].time < doubleClickTimeout
                    ) {
                        if (clicks[clicks.length - 1].value === clicks[clicks.length - 2].value) {
                            doubleClick(Number(newValueOption));
                        } else {
                            simpleClick([clicks[clicks.length - 2].value, clicks[clicks.length - 1].value]);
                        }
                    } else {
                        simpleClick(Number(newValueOption));
                    }

                    clicksRef.current = [];
                }, doubleClickTimeout);

                return () => {
                    window.clearTimeout(id);
                };
            }
        },
        [simpleClick, doubleClick, readOnly, periodicityOnDoubleClick]
    );

    if (mode === "single" && !periodicityOnDoubleClick) {
        if (disabled) {
            return <>{stringValue ? stringValue.join(",") : placeholder}</>;
        }

        return (
            <Select.Root value={stringValue && stringValue.join(",")} onValueChange={onOptionClick}>
                <Select.Trigger disabled={readOnly}>
                    <Select.Value placeholder={placeholder} />
                </Select.Trigger>
                <Select.Content>
                    {options.map((option) => (
                        <Select.Item key={option.value} value={option.value} disabled={readOnly}>
                            {option.label}
                        </Select.Item>
                    ))}
                </Select.Content>
            </Select.Root>
        );
    } else {
        if (disabled) {
            return <>{selectedLabels.length ? selectedLabels : placeholder}</>;
        }

        return (
            <MultiSelect
                noBadge
                createValueText={() => selectedLabels}
                placeholder={placeholder}
                selections={options}
                selectedValue={stringValue}
                listClassName="absolute"
                onValueChange={(value) => {
                    if (!readOnly) {
                        setValue(value.map((v) => Number(v)));
                    }
                }}
                disabled={readOnly}
            />
        );
    }
}

export default CustomSelect;
