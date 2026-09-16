import Alert from "@/components/base/Alert";
import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import Flex from "@/components/base/Flex";
import MultiSelect from "@/components/MultiSelect";
import Switch from "@/components/base/Switch";
import Toast from "@/components/base/Toast";
import { EMAIL_REGEX } from "@/constants";
import {
    TProjectEmailNotificationCategory,
    useGetProjectEmailNotificationPolicy,
    useUpdateProjectEmailNotificationPolicy,
} from "@/controllers/api/board/settings/useProjectEmailNotificationPolicy";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { memo, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const CATEGORIES: TProjectEmailNotificationCategory[] = ["board", "cards", "comments", "attachments", "checklists", "wiki"];

const BoardSettingsEmailNotifications = memo(() => {
    const [t] = useTranslation();
    const { project, canEditBasicInfo } = useBoardSettings();
    const { data: policy, isLoading, isError, refetch } = useGetProjectEmailNotificationPolicy(project.uid);
    const { mutateAsync, isPending } = useUpdateProjectEmailNotificationPolicy(project.uid);
    const [enabled, setEnabled] = useState(false);
    const [notifyAllMembers, setNotifyAllMembers] = useState(false);
    const [categories, setCategories] = useState<TProjectEmailNotificationCategory[]>([]);
    const [recipientUIDs, setRecipientUIDs] = useState<string[]>([]);
    const [externalEmails, setExternalEmails] = useState<string[]>([]);
    const [targetColumns, setTargetColumns] = useState<string[]>([]);

    useEffect(() => {
        if (!policy) return;
        setEnabled(policy.is_enabled);
        setNotifyAllMembers(policy.notify_all_members);
        setCategories(policy.categories);
        setRecipientUIDs(policy.recipient_user_uids);
        setExternalEmails(policy.external_recipient_emails);
        setTargetColumns(policy.card_move_target_columns);
    }, [policy]);

    if (isLoading) return <div className="py-4 text-sm text-muted-foreground">{t("common.Loading...")}</div>;
    if (isError || !policy) {
        return (
            <Alert variant="destructive" title={t("project.settings.Email notifications unavailable")}>
                <Button size="sm" variant="outline" onClick={() => void refetch()}>
                    {t("common.Retry")}
                </Button>
            </Alert>
        );
    }

    const toggle = <T,>(values: T[], value: T): T[] => (values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);
    const save = async () => {
        await Toast.Add.promise(
            mutateAsync({
                is_enabled: enabled,
                notify_all_members: notifyAllMembers,
                categories,
                recipient_user_uids: notifyAllMembers ? [] : recipientUIDs,
                external_recipient_emails: externalEmails,
                card_move_target_columns: targetColumns,
            }),
            {
                loading: t("common.Saving..."),
                success: t("successes.Email notification policy updated successfully."),
                error: (error) => (error instanceof Error ? error.message : t("errors.Internal server error")),
            }
        );
    };

    return (
        <Flex direction="col" gap="4" py="4" className="w-full max-w-2xl">
            {!policy.smtp_available && (
                <Alert variant="warning" icon="triangle-alert" title={t("project.settings.SMTP is not configured")}>
                    {t("project.settings.Configure SMTP before enabling board email notifications.")}
                </Alert>
            )}
            {policy.last_delivery_status === "failed" && (
                <Alert variant="destructive" title={t("project.settings.Recent email delivery failed")}>
                    <p className="text-sm">
                        {policy.last_delivery_recipient_email}
                        {policy.last_delivery_at ? ` · ${new Date(policy.last_delivery_at).toLocaleString()}` : ""}
                    </p>
                    {policy.last_delivery_error && <p className="text-xs">{policy.last_delivery_error}</p>}
                </Alert>
            )}
            <Switch
                checked={enabled}
                onCheckedChange={setEnabled}
                disabled={!canEditBasicInfo || !policy.smtp_available || isPending}
                label={t("project.settings.Send board updates by email")}
                description={t("project.settings.Email is sent only for the selected board events.")}
            />
            <div className="grid gap-2">
                <strong className="text-sm">{t("project.settings.Events")}</strong>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    {CATEGORIES.map((category) => (
                        <Checkbox
                            key={category}
                            checked={categories.includes(category)}
                            onCheckedChange={() => setCategories(toggle(categories, category))}
                            disabled={!canEditBasicInfo || isPending}
                            label={t(`project.settings.emailCategories.${category}`)}
                        />
                    ))}
                </div>
            </div>
            <div className="grid gap-2">
                <strong className="text-sm">{t("project.settings.Card move target")}</strong>
                <p className="text-xs text-muted-foreground">
                    {t("project.settings.Selecting a column limits card emails to moves into that column.")}
                </p>
                <div className="flex flex-wrap gap-3">
                    {policy.available_columns.map((column) => (
                        <Checkbox
                            key={column}
                            checked={targetColumns.includes(column)}
                            onCheckedChange={() => setTargetColumns(toggle(targetColumns, column))}
                            disabled={!canEditBasicInfo || isPending}
                            label={column}
                        />
                    ))}
                </div>
            </div>
            <div className="grid gap-3">
                <strong className="text-sm">{t("project.settings.Recipients")}</strong>
                <Checkbox
                    checked={notifyAllMembers}
                    onCheckedChange={(checked) => setNotifyAllMembers(checked === true)}
                    disabled={!canEditBasicInfo || isPending}
                    label={t("project.settings.All current board members")}
                    description={t("project.settings.The person who made the change is excluded.")}
                />
                {!notifyAllMembers &&
                    policy.available_recipients.map((recipient) => (
                        <Checkbox
                            key={recipient.uid}
                            checked={recipientUIDs.includes(recipient.uid)}
                            onCheckedChange={() => setRecipientUIDs(toggle(recipientUIDs, recipient.uid))}
                            disabled={!canEditBasicInfo || isPending}
                            label={`${recipient.firstname} ${recipient.lastname} · ${recipient.email}`}
                        />
                    ))}
                <div className="grid gap-2 pt-2">
                    <strong className="text-sm">{t("project.settings.External email recipients")}</strong>
                    <p className="text-xs text-muted-foreground">{t("project.settings.External recipients do not need a Langboard account.")}</p>
                    <MultiSelect
                        selections={externalEmails.map((email) => ({ label: email, value: email }))}
                        selectedValue={externalEmails}
                        onValueChange={(values) => setExternalEmails(values.map((value) => value.trim().toLowerCase()))}
                        placeholder={t("project.settings.Add an external email...")}
                        canCreateNew
                        validateCreatedNewValue={(value) => EMAIL_REGEX.test(value.trim())}
                        createNewCommandItemLabel={(values) => values[0]?.trim().toLowerCase() ?? ""}
                        disabled={!canEditBasicInfo || isPending}
                    />
                </div>
            </div>
            {canEditBasicInfo && (
                <Flex justify="end">
                    <Button onClick={() => void save()} disabled={isPending || (enabled && !policy.smtp_available)}>
                        {t("common.Save")}
                    </Button>
                </Flex>
            )}
        </Flex>
    );
});

export default BoardSettingsEmailNotifications;
