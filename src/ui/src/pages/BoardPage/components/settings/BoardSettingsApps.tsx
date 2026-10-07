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
    binding: { state: string; granted_capabilities: string[]; stage_transitions_enabled: boolean } | null;
}
const names = { github: "GitHub", glitchtip: "GlitchTip", dokploy: "Dokploy" };
export default function BoardSettingsApps() {
    const [t] = useTranslation();
    const { project } = useBoardSettings();
    const { query } = useQueryMutation();
    const { data, isLoading, isError, refetch } = query(
        ["board-app-catalog", project.uid],
        async () => (await api.get<{ apps: CatalogApp[] }>(`/board/${project.uid}/settings/apps`)).data.apps,
        { retry: 0 }
    );
    const [dirty, setDirty] = useState(false);
    const [selected, setSelected] = useState<"github" | "glitchtip" | null>(null);
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
                        {(data ?? []).map(({ key, name, binding, workflow_requirements }) => (
                            <article key={key} className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
                                <h4 className="font-semibold">{name}</h4>
                                <span className="self-start rounded-md bg-muted px-2 py-1 text-xs">
                                    {t(`project.settings.App state ${binding?.state ?? "unconfigured"}`)}
                                </span>
                                <p className="flex-1 text-sm text-muted-foreground">{t(`project.settings.App ${key} summary`)}</p>
                                <p className="text-xs text-muted-foreground">{t("project.settings.App connection setup pending")}</p>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={!workflow_requirements || (key !== "github" && key !== "glitchtip")}
                                    onClick={() => (key === "github" || key === "glitchtip") && setSelected(key)}
                                >
                                    {t(`project.settings.${key === "dokploy" ? "App workflow contract pending" : "Configure workflow"}`)}
                                </Button>
                            </article>
                        ))}
                    </div>
                </>
            )}
        </div>
    );
}
