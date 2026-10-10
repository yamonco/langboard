import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Card from "@/components/base/Card";
import Checkbox from "@/components/base/Checkbox";
import Collapsible from "@/components/base/Collapsible";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Select from "@/components/base/Select";
import Toast from "@/components/base/Toast";
import Collaborative from "@/components/Collaborative";
import CollaborativeControlOverlay from "@/components/Collaborative/ControlOverlay";
import type { ICollaborativeTextMeta } from "@/components/Collaborative/useCollaborativeText";
import { useCollaborativeText } from "@/components/Collaborative/useCollaborativeText";
import Cron from "@/components/Cron";
import useDeleteNotificationScheduleRule from "@/controllers/api/settings/notificationSchedule/useDeleteNotificationScheduleRule";
import useUpdateNotificationScheduleRule from "@/controllers/api/settings/notificationSchedule/useUpdateNotificationScheduleRule";
import type { IUpdateNotificationScheduleRuleForm } from "@/controllers/api/settings/notificationSchedule/useUpdateNotificationScheduleRule";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { NotificationScheduleRuleModel } from "@/core/models";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { ROUTES } from "@/core/routing/constants";
import RuleSelect from "@/pages/SettingsPage/components/notificationSchedule/RuleSelect";
import {
    getNotificationScheduleTimezone,
    normalizeNotificationRule,
    parseNotificationRuleValue,
    type TNotificationRuleValue,
} from "@/pages/SettingsPage/components/notificationSchedule/utils";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { EHttpStatus } from "@langboard/core/enums";
import { Utils } from "@langboard/core/utils";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface INotificationRuleEditorProps {
    rule: NotificationScheduleRuleModel.TModel;
    schema: NotificationScheduleRuleModel.IRuleSchema | null;
    disabled: bool;
    isExpanded: bool;
    isSelected: bool;
    canDelete: bool;
    onSelect: () => void;
    onToggle: () => void;
}

interface IRuleControlMeta {
    field: string;
    label: string;
    updatedAt: number;
}

const isRuleControlMeta = (value: unknown): value is IRuleControlMeta => {
    if (!value || typeof value !== "object") {
        return false;
    }

    const meta = value as Partial<IRuleControlMeta>;
    return typeof meta.field === "string" && typeof meta.label === "string" && typeof meta.updatedAt === "number";
};

function NotificationRuleEditor({ rule, schema, disabled, isExpanded, isSelected, canDelete, onSelect, onToggle }: INotificationRuleEditorProps) {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { setIsValidating } = useAppSetting();
    const { mutateAsync: updateNotificationScheduleRuleMutateAsync } = useUpdateNotificationScheduleRule(rule, { interceptToast: true });
    const { mutateAsync: deleteNotificationScheduleRuleMutateAsync } = useDeleteNotificationScheduleRule(rule, { interceptToast: true });
    const [isEditing, setIsEditing] = useState(false);
    const [editingOriginalRule, setEditingOriginalRule] = useState<TNotificationRuleValue | null>(null);
    const [draftRule, setDraftRule] = useState<TNotificationRuleValue | null>(null);
    const editingOriginalRuleRef = useRef<TNotificationRuleValue | null>(null);
    const initializedDraftRef = useRef(false);
    const ignoreRemoteDraftRef = useRef(false);
    const ignoreRemoteDraftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const isApplyingRemoteDraftRef = useRef(false);
    const editStartedAtRef = useRef(0);
    const remoteDraftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const name = rule.useField("name");
    const isEnabled = rule.useField("is_enabled");
    const rawIntervalStr = rule.useField("interval_str");
    const intervalStr = useMemo(() => Utils.String.Crontab.restoreTimezone(rawIntervalStr), [rawIntervalStr]);
    const target = rule.useField("target");
    const field = rule.useField("field");
    const operator = rule.useField("operator");
    const value = rule.useField("value");
    const recipients = rule.useField("recipients");
    const repeatAfterHours = rule.useField("repeat_after_hours");
    const ruleValue: TNotificationRuleValue = {
        name,
        is_enabled: isEnabled,
        interval_str: intervalStr,
        target,
        field,
        operator,
        value,
        recipients,
        repeat_after_hours: repeatAfterHours,
    };
    const normalizedRuleValue = normalizeNotificationRule(ruleValue, schema);
    const isFormDisabled = disabled || !isEditing;
    const updateRule = (nextRule: TNotificationRuleValue) => {
        rule.name = nextRule.name;
        rule.is_enabled = nextRule.is_enabled;
        rule.interval_str = nextRule.interval_str;
        rule.target = nextRule.target;
        rule.field = nextRule.field;
        rule.operator = nextRule.operator;
        rule.value = nextRule.value;
        rule.recipients = nextRule.recipients;
        rule.repeat_after_hours = nextRule.repeat_after_hours;
    };

    const collaborativeDocument = {
        collaborationType: EEditorCollaborationType.AppSettings,
        uid: rule.uid,
        section: "notification-schedule-rule",
    } as const;
    const parseRuleDraft = (value: string): TNotificationRuleValue => {
        try {
            const parsed = JSON.parse(value) as Partial<TNotificationRuleValue>;
            return normalizeNotificationRule(
                {
                    ...ruleValue,
                    ...parsed,
                    recipients: Array.isArray(parsed.recipients)
                        ? parsed.recipients.filter((item): item is string => typeof item === "string")
                        : recipients,
                },
                schema
            );
        } catch {
            return normalizedRuleValue;
        }
    };

    const ruleDraftSync = useCollaborativeText({
        ...collaborativeDocument,
        field: "rule",
        defaultValue: JSON.stringify(normalizedRuleValue),
        disabled: isFormDisabled,
        onValueChange: (nextValue) => {
            if (ignoreRemoteDraftRef.current) {
                return;
            }

            isApplyingRemoteDraftRef.current = true;
            if (remoteDraftTimerRef.current) {
                clearTimeout(remoteDraftTimerRef.current);
            }
            const nextRule = parseRuleDraft(nextValue);
            setDraftRule(nextRule);
            updateRule(nextRule);
            remoteDraftTimerRef.current = setTimeout(() => {
                isApplyingRemoteDraftRef.current = false;
                remoteDraftTimerRef.current = null;
            }, 0);
        },
    });
    useEffect(() => {
        if (!isEditing || !editingOriginalRule || initializedDraftRef.current) {
            return;
        }

        if (ruleDraftSync.remoteCursors.length || ruleDraftSync.remoteMeta.length) {
            initializedDraftRef.current = true;
            return;
        }

        initializedDraftRef.current = true;
        ruleDraftSync.resetValue(JSON.stringify(editingOriginalRule));
        if (ignoreRemoteDraftTimerRef.current) {
            clearTimeout(ignoreRemoteDraftTimerRef.current);
        }
        ignoreRemoteDraftTimerRef.current = setTimeout(() => {
            ignoreRemoteDraftRef.current = false;
            ignoreRemoteDraftTimerRef.current = null;
        }, 0);
    }, [editingOriginalRule, isEditing, ruleDraftSync]);

    useEffect(() => {
        return () => {
            if (remoteDraftTimerRef.current) {
                clearTimeout(remoteDraftTimerRef.current);
            }
            if (ignoreRemoteDraftTimerRef.current) {
                clearTimeout(ignoreRemoteDraftTimerRef.current);
            }
        };
    }, []);
    const remoteControlMeta = useMemo(() => {
        return ruleDraftSync.remoteMeta.reduce<Record<string, ICollaborativeTextMeta<IRuleControlMeta>>>((acc, meta) => {
            if (!isRuleControlMeta(meta.value)) {
                return acc;
            }

            const parsedMeta = meta as ICollaborativeTextMeta<IRuleControlMeta>;
            if (parsedMeta.value.updatedAt < editStartedAtRef.current) {
                return acc;
            }

            const previousMeta = acc[parsedMeta.value.field];
            if (!previousMeta || previousMeta.value.updatedAt < parsedMeta.value.updatedAt) {
                acc[parsedMeta.value.field] = parsedMeta;
            }

            return acc;
        }, {});
    }, [ruleDraftSync.remoteMeta]);

    const syncRule = (nextRule: TNotificationRuleValue) => {
        const normalizedRule = normalizeNotificationRule(nextRule, schema);
        const serializedRule = JSON.stringify(normalizedRule);

        if (serializedRule === ruleDraftSync.value) {
            setDraftRule(normalizedRule);
            updateRule(normalizedRule);
            return;
        }

        setDraftRule(normalizedRule);
        updateRule(normalizedRule);
        ruleDraftSync.updateValue(serializedRule);
    };
    const updateControlMeta = (field: string, label: string) => {
        if (isApplyingRemoteDraftRef.current) {
            return;
        }

        ruleDraftSync.updateMeta({
            field,
            label,
            updatedAt: Date.now(),
        } satisfies IRuleControlMeta);
    };
    const getControlMeta = (field: string) => {
        return remoteControlMeta[field];
    };
    const renderControlOverlay = (field: string, placement: "control" | "checkbox" = "control") => {
        const meta = getControlMeta(field);
        if (!meta) {
            return null;
        }

        return (
            <CollaborativeControlOverlay
                color={meta.color}
                labelClassName={
                    placement === "checkbox" ? "absolute right-0 z-[9999] max-w-32 truncate" : "absolute right-2 z-[9999] max-w-32 truncate"
                }
                labelStyle={{ top: "-0.75rem" }}
                name={meta.name}
                title={t("common.User changed field", { name: meta.name, field: meta.value.label })}
            />
        );
    };
    const renderControlFrame = (field: string, children: ReactNode) => {
        return (
            <div className="relative">
                {children}
                {renderControlOverlay(field)}
            </div>
        );
    };
    const renderFieldLabel = (label: string) => {
        return <label className="text-sm font-medium">{label}</label>;
    };

    const syncedRuleValue = isEditing
        ? draftRule || editingOriginalRuleRef.current || editingOriginalRule || normalizedRuleValue
        : normalizedRuleValue;
    const syncedIsEnabled = syncedRuleValue.is_enabled;
    const syncedIntervalStr = syncedRuleValue.interval_str;
    const syncedTarget = syncedRuleValue.target;
    const syncedTargetSchema = schema?.targets.find((targetSchema) => targetSchema.key === syncedTarget);
    const syncedField = syncedRuleValue.field;
    const syncedFieldSchema = syncedTargetSchema?.fields.find((fieldSchema) => fieldSchema.key === syncedField);
    const syncedOperator = syncedRuleValue.operator;
    const syncedOperatorSchema = syncedOperator ? schema?.operators[syncedOperator] : null;
    const syncedDynamicValues = schema?.values[`${syncedTarget}.${syncedField}`] || [];
    const syncedRecipients = syncedRuleValue.recipients;
    const handleError = (error: unknown) => {
        const messageRef = { message: "" };
        const { handle } = setupApiErrorHandler(
            {
                [EHttpStatus.HTTP_403_FORBIDDEN]: {
                    after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                },
            },
            messageRef
        );

        handle(error);
        return messageRef.message;
    };

    const saveRule = () => {
        if (disabled || !isEditing) {
            return;
        }

        const normalizedRule = normalizeNotificationRule(syncedRuleValue, schema);
        if (
            !normalizedRule.name.trim() ||
            !normalizedRule.target ||
            !normalizedRule.field ||
            !normalizedRule.operator ||
            !normalizedRule.recipients.length
        ) {
            Toast.Add.error(t("settings.Notification rule is invalid."));
            return;
        }

        setIsValidating(true);
        const ruleForm: IUpdateNotificationScheduleRuleForm = {
            name: normalizedRule.name,
            is_enabled: normalizedRule.is_enabled,
            interval_str: normalizedRule.interval_str,
            timezone: getNotificationScheduleTimezone(),
            target: normalizedRule.target,
            field: normalizedRule.field,
            operator: normalizedRule.operator,
            value: normalizedRule.value,
            recipients: normalizedRule.recipients,
            repeat_after_hours: normalizedRule.repeat_after_hours,
        };
        const promise = updateNotificationScheduleRuleMutateAsync(ruleForm);

        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: handleError,
            success: () => t("successes.Notification schedule saved successfully."),
            finally: () => {
                ruleDraftSync.updateValue(JSON.stringify(normalizedRule));
                setIsValidating(false);
                ruleDraftSync.updateMeta(null);
                editStartedAtRef.current = 0;
                editingOriginalRuleRef.current = null;
                initializedDraftRef.current = false;
                ignoreRemoteDraftRef.current = false;
                setDraftRule(null);
                setEditingOriginalRule(null);
                setIsEditing(false);
            },
        });
    };

    const deleteRule = () => {
        if (disabled || !canDelete) {
            return;
        }

        setIsValidating(true);
        const promise = deleteNotificationScheduleRuleMutateAsync({});

        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: handleError,
            success: () => t("successes.Notification schedule rule deleted successfully."),
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    const startEditing = () => {
        if (disabled) {
            return;
        }

        const originalRule = normalizeNotificationRule(ruleValue, schema);
        editStartedAtRef.current = Date.now();
        initializedDraftRef.current = false;
        ignoreRemoteDraftRef.current = true;
        setDraftRule(originalRule);
        ruleDraftSync.updateMeta(null);
        updateRule(originalRule);
        editingOriginalRuleRef.current = originalRule;
        setEditingOriginalRule(originalRule);
        setIsEditing(true);
    };

    const cancelEditing = () => {
        const originalRule = editingOriginalRuleRef.current || editingOriginalRule || normalizeNotificationRule(ruleValue, schema);
        updateRule(originalRule);
        ruleDraftSync.resetValue(JSON.stringify(originalRule));
        ruleDraftSync.updateMeta(null);
        editStartedAtRef.current = 0;
        editingOriginalRuleRef.current = null;
        initializedDraftRef.current = false;
        ignoreRemoteDraftRef.current = false;
        setDraftRule(null);
        setEditingOriginalRule(null);
        setIsEditing(false);
    };

    const changeTarget = (target: string) => {
        const nextTargetSchema = schema?.targets.find((item) => item.key === target);
        const nextField = nextTargetSchema?.fields[0];
        const nextRule = normalizeNotificationRule(
            {
                ...syncedRuleValue,
                target,
                field: nextField?.key || "",
                operator: nextField?.operators[0] || "",
                recipients: nextTargetSchema?.recipients.slice(0, 1) || [],
            },
            schema
        );

        syncRule(nextRule);
    };

    const changeIsEnabled = (checked: bool) => {
        syncRule({ ...syncedRuleValue, is_enabled: checked });
    };

    const changeIntervalStr = (intervalStr: string) => {
        syncRule({ ...syncedRuleValue, interval_str: intervalStr });
    };

    const changeField = (field: string) => {
        const nextFieldSchema = syncedTargetSchema?.fields.find((item) => item.key === field);
        const nextRule = normalizeNotificationRule({ ...syncedRuleValue, field, operator: nextFieldSchema?.operators[0] || "" }, schema);

        syncRule(nextRule);
    };

    const changeOperator = (operator: string) => {
        const nextRule = normalizeNotificationRule({ ...syncedRuleValue, operator }, schema);

        syncRule(nextRule);
    };

    const changeDynamicValue = (value: string) => {
        const nextValue = parseNotificationRuleValue(value);

        syncRule({ ...syncedRuleValue, value: nextValue });
    };

    const changeRecipients = (recipients: string[]) => {
        syncRule({ ...syncedRuleValue, recipients });
    };

    const changeRepeatAfterHours = (repeatAfterHours: string) => {
        syncRule({ ...syncedRuleValue, repeat_after_hours: Number(repeatAfterHours) });
    };

    const changeNumericValue = (value: string) => {
        syncRule({ ...syncedRuleValue, value: Number(value) });
    };

    const changeName = (name: string) => {
        syncRule({ ...syncedRuleValue, name });
    };

    const changeEnabledState = (checked: bool | "indeterminate") => {
        if (checked === syncedRuleValue.is_enabled) {
            return;
        }

        updateControlMeta("is_enabled", t("settings.Enabled"));
        changeIsEnabled(checked === true);
    };

    const changeRecipientState = (recipient: string, checked: bool | "indeterminate") => {
        if ((checked === true) === syncedRuleValue.recipients.includes(recipient)) {
            return;
        }

        updateControlMeta(`recipient:${recipient}`, t(`settings.notificationSchedules.recipients.${recipient}`));
        const nextRecipients =
            checked === true
                ? Array.from(new Set([...syncedRuleValue.recipients, recipient]))
                : syncedRuleValue.recipients.filter((item) => item !== recipient);
        changeRecipients(nextRecipients);
    };

    const changeCronValue = (value: string) => {
        if (value === syncedRuleValue.interval_str) {
            return;
        }

        updateControlMeta("interval_str", t("settings.Schedule"));
        changeIntervalStr(value);
    };

    const changeTargetValue = (target: string) => {
        if (target === syncedRuleValue.target) {
            return;
        }

        updateControlMeta("target", t("settings.Target"));
        changeTarget(target);
    };

    const changeFieldValue = (field: string) => {
        if (field === syncedRuleValue.field) {
            return;
        }

        updateControlMeta("field", t("settings.Field"));
        changeField(field);
    };

    const changeOperatorValue = (operator: string) => {
        if (operator === syncedRuleValue.operator) {
            return;
        }

        updateControlMeta("operator", t("settings.Operator"));
        changeOperator(operator);
    };

    const changeDynamicRuleValue = (nextValue: string) => {
        if (nextValue === String(syncedRuleValue.value ?? "")) {
            return;
        }

        updateControlMeta("value", t("settings.Value"));
        changeDynamicValue(nextValue);
    };

    return (
        <Collapsible.Root open={isExpanded} onOpenChange={onToggle}>
            <Card.Root className="rounded-md shadow-none">
                <Card.Header className="p-4">
                    <Flex items="center" justify="between" gap="3">
                        <Flex items="center" gap="3" className="min-w-0 flex-1">
                            {canDelete && <Checkbox checked={isSelected} onClick={onSelect} aria-label={t("settings.Select rule")} />}
                            <Box className="min-w-0 flex-1">
                                <Collaborative.Input
                                    {...collaborativeDocument}
                                    field="name"
                                    defaultValue={syncedRuleValue.name}
                                    onValueChange={changeName}
                                    disabled={isFormDisabled}
                                />
                                <div className="mt-1 truncate text-xs text-muted-foreground">{getRuleSummary(syncedRuleValue, schema, t)}</div>
                            </Box>
                        </Flex>
                        <Flex items="center" gap="3">
                            <div className="relative">
                                <Checkbox
                                    checked={syncedIsEnabled}
                                    onCheckedChange={changeEnabledState}
                                    disabled={isFormDisabled}
                                    label={t("settings.Enabled")}
                                />
                                {renderControlOverlay("is_enabled", "checkbox")}
                            </div>
                            <Collapsible.Trigger asChild>
                                <Button variant="ghost" size="icon-sm">
                                    <IconComponent icon={isExpanded ? "chevron-up" : "chevron-down"} size="4" />
                                </Button>
                            </Collapsible.Trigger>
                            {isEditing ? (
                                <>
                                    <Button variant="secondary" size="sm" onClick={cancelEditing} disabled={disabled}>
                                        {t("common.Cancel")}
                                    </Button>
                                    <Button variant="outline" size="sm" onClick={saveRule} disabled={disabled}>
                                        {t("common.Save")}
                                    </Button>
                                </>
                            ) : (
                                <Button variant="outline" size="sm" onClick={startEditing} disabled={disabled}>
                                    {t("common.Edit")}
                                </Button>
                            )}
                            <Button variant="destructive-ghost" size="icon-sm" onClick={deleteRule} disabled={disabled || !canDelete}>
                                <IconComponent icon="trash-2" size="4" />
                            </Button>
                        </Flex>
                    </Flex>
                </Card.Header>
                <Collapsible.Content className="overflow-hidden data-[state=closed]:animate-collapse-up data-[state=open]:animate-collapse-down">
                    <Card.Content className="space-y-4 p-4 pt-0">
                        <Box className="space-y-2">
                            {renderFieldLabel(t("settings.Schedule"))}
                            {renderControlFrame(
                                "interval_str",
                                <Cron value={syncedIntervalStr} setValue={changeCronValue} disabled={isFormDisabled} readOnly={isFormDisabled} />
                            )}
                        </Box>
                        <Flex direction={{ initial: "col", md: "row" }} gap="3">
                            <RuleSelect
                                label={t("settings.Target")}
                                remoteMeta={getControlMeta("target")}
                                value={syncedTarget}
                                values={(schema?.targets || []).map((target) => target.key)}
                                disabled={isFormDisabled}
                                onChange={changeTargetValue}
                            />
                            <RuleSelect
                                label={t("settings.Field")}
                                remoteMeta={getControlMeta("field")}
                                value={syncedField}
                                values={(syncedTargetSchema?.fields || []).map((field) => field.key)}
                                disabled={isFormDisabled}
                                onChange={changeFieldValue}
                            />
                            <RuleSelect
                                label={t("settings.Operator")}
                                remoteMeta={getControlMeta("operator")}
                                value={syncedOperator}
                                values={syncedFieldSchema?.operators || []}
                                disabled={isFormDisabled}
                                onChange={changeOperatorValue}
                            />
                        </Flex>
                        {syncedOperatorSchema?.value_type !== "none" && (
                            <Box className="space-y-2">
                                {renderFieldLabel(t("settings.Value"))}
                                {syncedOperatorSchema?.value_type === "dynamic" && syncedDynamicValues.length ? (
                                    <div className="relative">
                                        <Select.Root
                                            value={String(syncedRuleValue.value ?? syncedDynamicValues[0])}
                                            onValueChange={changeDynamicRuleValue}
                                            disabled={isFormDisabled}
                                        >
                                            <Select.Trigger>
                                                <Select.Value />
                                            </Select.Trigger>
                                            <Select.Content>
                                                {syncedDynamicValues.map((value) => (
                                                    <Select.Item key={`${rule.uid}-value-${String(value)}`} value={String(value)}>
                                                        {t(`settings.notificationSchedules.ruleValues.${String(value)}`)}
                                                    </Select.Item>
                                                ))}
                                            </Select.Content>
                                        </Select.Root>
                                        {renderControlOverlay("value")}
                                    </div>
                                ) : (
                                    <Collaborative.Input
                                        type="number"
                                        {...collaborativeDocument}
                                        field="value"
                                        min={syncedOperatorSchema?.min ?? 0}
                                        defaultValue={String(syncedRuleValue.value ?? 0)}
                                        onValueChange={changeNumericValue}
                                        disabled={isFormDisabled}
                                    />
                                )}
                            </Box>
                        )}
                        <Box className="space-y-2">
                            <div className="text-sm font-medium">{t("settings.Recipients")}</div>
                            <Flex wrap gap="3">
                                {(syncedTargetSchema?.recipients || []).map((recipient) => (
                                    <div key={`${rule.uid}-${recipient}`} className="relative">
                                        <Checkbox
                                            checked={syncedRecipients.includes(recipient)}
                                            onCheckedChange={(checked) => changeRecipientState(recipient, checked)}
                                            disabled={isFormDisabled}
                                            label={t(`settings.notificationSchedules.recipients.${recipient}`)}
                                        />
                                        {renderControlOverlay(`recipient:${recipient}`, "checkbox")}
                                    </div>
                                ))}
                            </Flex>
                        </Box>
                        <Box className="space-y-2">
                            <label className="text-sm font-medium">{t("settings.Repeat after hours")}</label>
                            <Collaborative.Input
                                type="number"
                                {...collaborativeDocument}
                                field="repeat_after_hours"
                                min={1}
                                defaultValue={String(syncedRuleValue.repeat_after_hours || 24)}
                                onValueChange={changeRepeatAfterHours}
                                disabled={isFormDisabled}
                            />
                        </Box>
                    </Card.Content>
                </Collapsible.Content>
            </Card.Root>
        </Collapsible.Root>
    );
}

function getRuleSummary(
    rule: TNotificationRuleValue,
    schema: NotificationScheduleRuleModel.IRuleSchema | null,
    t: ReturnType<typeof useTranslation>[0]
) {
    const operatorSchema = rule.operator ? schema?.operators[rule.operator] : null;
    const valueText =
        operatorSchema?.value_type && operatorSchema.value_type !== "none"
            ? ` ${rule.value === null || rule.value === undefined ? "" : String(rule.value)}`
            : "";

    return [
        t(`settings.notificationSchedules.ruleSchema.${rule.target}`),
        t(`settings.notificationSchedules.ruleSchema.${rule.field}`),
        `${t(`settings.notificationSchedules.ruleSchema.${rule.operator}`)}${valueText}`,
        rule.recipients.map((recipient) => t(`settings.notificationSchedules.recipients.${recipient}`)).join(", "),
    ]
        .filter(Boolean)
        .join(" / ");
}

export default NotificationRuleEditor;
