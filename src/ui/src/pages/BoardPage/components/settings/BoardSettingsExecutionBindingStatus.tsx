import Alert from "@/components/base/Alert";
import Button from "@/components/base/Button";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { useTranslation } from "react-i18next";

interface IBindingStatus {
    binding: { is_enabled: boolean } | null;
    binding_status: { state: "valid" | "binding_invalid" | "unconfigured"; reasons: string[] };
}

const reasonLabels: Record<string, string> = {
    binding_disabled: "Binding is disabled",
    project_missing: "Board is missing",
    event_not_bound: "work.ready is not bound",
    webhook_missing: "Webhook was deleted",
    webhook_disabled: "Webhook is disabled",
    event_not_allowed: "Webhook no longer allows work.ready",
    signing_secret_missing: "Signing secret is missing",
    signing_secret_unavailable: "Signing secret is unavailable",
    column_semantics_invalid: "Ready or terminal column is missing",
    column_invalid: "A bound column was deleted or archived",
    relationship_type_invalid: "Prerequisite relationship type is missing",
};

export default function BoardSettingsExecutionBindingStatus(): React.JSX.Element | null {
    const [t] = useTranslation();
    const { project } = useBoardSettings();
    const { query } = useQueryMutation();
    const { data, isError, refetch } = query(
        ["execution-binding-status", project.uid],
        async () => {
            return (await api.get(`/board/${project.uid}/settings/execution-binding`)).data as IBindingStatus;
        },
        { retry: 0 }
    );

    if (isError) {
        return (
            <Alert variant="destructive" title={t("project.settings.Execution binding unavailable")}>
                <Button size="sm" variant="outline" onClick={() => void refetch()}>{t("common.Retry")}</Button>
            </Alert>
        );
    }
    if (!data?.binding) return null;
    if (data.binding_status.state === "valid") {
        return <Alert variant="success" title={t("project.settings.Execution binding valid")} />;
    }
    return (
        <Alert variant="destructive" title={t("project.settings.Execution binding invalid")}>
            <ul className="list-disc pl-5 text-sm">
                {data.binding_status.reasons.map((reason) => <li key={reason}>{reasonLabels[reason] ?? reason}</li>)}
            </ul>
        </Alert>
    );
}
