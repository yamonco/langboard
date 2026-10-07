import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import { useQueryMutation } from "@/core/helpers/QueryMutation";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import Button from "@/components/base/Button";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";

interface CatalogApp {
    key: string;
    name: string;
    workflow_requirements: { required: string[]; optional: string[] } | null;
    resources: {
        selected_count: number;
        access_counts: Record<string, number>;
        health_counts: Record<string, number>;
        connection_counts: Record<string, number>;
    };
    binding: { uid: string; revision: string; state: string; granted_capabilities: string[]; stage_transitions_enabled: boolean } | null;
}
const names = { github: "GitHub", glitchtip: "GlitchTip", dokploy: "Dokploy" };
export default function BoardSettingsApps() {
    const [t] = useTranslation();
    const { project, canEditBasicInfo } = useBoardSettings();
    const { query } = useQueryMutation();
    const { data, isLoading, isError, refetch } = query(
        ["board-app-catalog", project.uid],
        async () => (await api.get<{ apps: CatalogApp[] }>(`/board/${project.uid}/settings/apps`)).data.apps,
        { retry: 0 }
    );
    const [pending, setPending] = useState(false);
    const [disableTarget, setDisableTarget] = useState<string | null>(null);
    const [error, setError] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [selected, setSelected] = useState<"github" | "glitchtip" | null>(null);
    const disable = async (app: CatalogApp) => {
        if (pending || !canEditBasicInfo || !app.binding) return;
        setPending(true);
        setError(false);
        try {
            await api.post(`/board/${project.uid}/settings/apps/${app.key}/disable`, {
                binding_uid: app.binding.uid,
                expected_revision: app.binding.revision,
            });
            setDisableTarget(null);
            await refetch();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    return (
        <div className="flex w-full flex-col gap-4 py-4">
            {selected ? (
                <>
                    <Button
                        size="sm"
                        variant="outline"
                        className="self-start"
                        disabled={dirty}
                        onClick={() => {
                            setSelected(null);
                            void refetch();
                        }}
                    >
                        {t("project.settings.Back to App Store")}
                    </Button>
                    <h3 className="text-base font-semibold">{names[selected]}</h3>
                    <BoardSettingsAppWorkflow key={selected} appKey={selected} onDirtyChange={setDirty} />
                </>
            ) : (
                <>
                    {error && <p role="alert">{t("project.settings.App workflow save failed")}</p>}
                    <h3 className="text-base font-semibold">{t("project.settings.App Store")}</h3>
                    <p className="text-sm text-muted-foreground">{t("project.settings.App Store help")}</p>
                    {isLoading && <p role="status">{t("common.Loading...")}</p>}
                    {isError && (
                        <div role="alert">
                            {t("project.settings.App workflow unavailable")}
                            <Button size="sm" variant="outline" onClick={() => void refetch()}>
                                {t("common.Retry")}
                            </Button>
                        </div>
                    )}
                    <div className="grid gap-3 sm:grid-cols-3">
                        {(data ?? []).map(({ key, name, binding, workflow_requirements, resources }) => (
                            <article key={key} className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
                                <h4 className="font-semibold">{name}</h4>
                                <span className="self-start rounded-md bg-muted px-2 py-1 text-xs">
                                    {t(`project.settings.App state ${binding?.state ?? "unconfigured"}`)}
                                </span>
                                {resources && (
                                    <details className="rounded-md border p-2 text-xs">
                                        <summary className="cursor-pointer">
                                            {t("project.settings.Selected App resources", { count: resources.selected_count })}
                                        </summary>
                                        <p className="mt-2 text-muted-foreground">{t("project.settings.App stored resource status help")}</p>
                                        {resources.selected_count === 0 ? (
                                            <p className="mt-2">{t("project.settings.No selected App resources")}</p>
                                        ) : (
                                            Object.entries({
                                                access: resources.access_counts,
                                                health: resources.health_counts,
                                                connection: resources.connection_counts,
                                            }).map(([category, counts]) => (
                                                <div key={category} className="mt-2 flex flex-wrap gap-1">
                                                    <span>{t(`project.settings.App resource ${category}`)}:</span>
                                                    {Object.entries(counts).map(([state, count]) => (
                                                        <span key={state} className="rounded bg-muted px-1.5">
                                                            {t(`project.settings.App resource state ${state}`)} · {count}
                                                        </span>
                                                    ))}
                                                </div>
                                            ))
                                        )}
                                    </details>
                                )}
                                <p className="flex-1 text-sm text-muted-foreground">{t(`project.settings.App ${key} summary`)}</p>
                                <p className="text-xs text-muted-foreground">{t("project.settings.App connection setup pending")}</p>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={pending || !workflow_requirements || (key !== "github" && key !== "glitchtip")}
                                    onClick={() => (key === "github" || key === "glitchtip") && setSelected(key)}
                                >
                                    {t(`project.settings.${key === "dokploy" ? "App workflow contract pending" : "Configure workflow"}`)}
                                </Button>
                                {binding &&
                                    binding.state !== "disabled" &&
                                    (disableTarget === key ? (
                                        <div className="flex flex-col gap-2">
                                            <p className="text-xs">{t("project.settings.Disable App help")}</p>
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                disabled={!canEditBasicInfo || pending}
                                                onClick={() => void disable({ key, name, binding, workflow_requirements, resources })}
                                            >
                                                {t("project.settings.Confirm disable App")}
                                            </Button>
                                            <Button size="sm" variant="ghost" disabled={pending} onClick={() => setDisableTarget(null)}>
                                                {t("common.Cancel")}
                                            </Button>
                                        </div>
                                    ) : (
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            disabled={!canEditBasicInfo || pending}
                                            onClick={() => setDisableTarget(key)}
                                        >
                                            {t("project.settings.Disable App")}
                                        </Button>
                                    ))}
                            </article>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
