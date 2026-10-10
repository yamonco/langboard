import { useState } from "react";
import { useTranslation } from "react-i18next";
import { api } from "@/core/helpers/Api";
import { formatNumber } from "@/core/utils/LocaleFormat";
import useBoardAppCatalog, { type CatalogApp } from "@/controllers/api/board/useBoardAppCatalog";
import { deletePanelState } from "@/core/apps/PanelSession";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import BoardSettingsGitHub from "./BoardSettingsGitHub";
import BoardSettingsGlitchTip from "./BoardSettingsGlitchTip";
import BoardSettingsDokploy from "./BoardSettingsDokploy";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";
import BoardSettingsInboundConnections from "./BoardSettingsInboundConnections";
import BoardSettingsAppConsent from "./BoardSettingsAppConsent";

export default function BoardSettingsApps() {
    const [t, i18n] = useTranslation();
    const { project, canEditBasicInfo, currentUser } = useBoardSettings();
    const { data, isLoading, isError, refetch } = useBoardAppCatalog(project.uid, currentUser?.uid);
    const [panelTarget, setPanelTarget] = useState<string | null>(null);
    const [readSignals, setReadSignals] = useState(false);
    const [pending, setPending] = useState(false);
    const [disableTarget, setDisableTarget] = useState<string | null>(null);
    const [error, setError] = useState(false);
    const [dirty, setDirty] = useState(false);
    const [connections, setConnections] = useState<CatalogApp | null>(null);
    const [selected, setSelected] = useState<CatalogApp | null>(null);
    const disable = async (app: CatalogApp) => {
        if (pending || !canEditBasicInfo || !app.binding) return;
        setPending(true);
        setError(false);
        try {
            await api.post(`/board/${project.uid}/settings/apps/${app.key}/disable`, {
                binding_uid: app.binding.uid,
                expected_revision: app.binding.revision,
            });
            if (currentUser) deletePanelState(JSON.stringify([currentUser.uid, project.uid, app.key, app.version]));
            setDisableTarget(null);
            await refetch();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    const setPanel = async (app: CatalogApp, enabled: boolean) => {
        if (pending || !canEditBasicInfo || !app.app_revision) return;
        setPending(true);
        setError(false);
        try {
            await api.put(`/board/${project.uid}/settings/apps/${encodeURIComponent(app.key)}/panel`, {
                binding_uid: app.binding?.uid ?? null,
                expected_revision: app.binding?.revision ?? null,
                app_revision: app.app_revision,
                enabled,
                read_signals: enabled && app.capabilities.includes("signals.read") && readSignals,
            });
            if (!enabled && currentUser) deletePanelState(JSON.stringify([currentUser.uid, project.uid, app.key, app.version]));
            setPanelTarget(null);
            await refetch();
        } catch {
            setError(true);
        } finally {
            setPending(false);
        }
    };
    return (
        <div className="flex w-full flex-col gap-4 py-4">
            {connections ? (
                <>
                    <Button
                        size="sm"
                        variant="outline"
                        className="self-start"
                        disabled={dirty}
                        onClick={() => {
                            setConnections(null);
                            void refetch();
                        }}
                    >
                        {t("project.settings.Back to App Store")}
                    </Button>
                    <BoardSettingsInboundConnections key={connections.key} app={connections} onBusy={setDirty} />
                </>
            ) : selected ? (
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
                    <h3 className="text-base font-semibold">{selected.name}</h3>
                    <BoardSettingsAppWorkflow key={selected.key} appKey={selected.key} onDirtyChange={setDirty} />
                </>
            ) : (
                <>
                    {error && <p role="alert">{t("project.settings.App workflow save failed")}</p>}
                    <h3 className="text-base font-semibold">{t("project.settings.App Store")}</h3>
                    <BoardSettingsGitHub onStatusChange={() => void refetch()} />
                    <BoardSettingsGlitchTip key={`${project.uid}:${canEditBasicInfo}`} onStatusChange={() => void refetch()} />
                    <BoardSettingsDokploy key={`dokploy:${project.uid}:${canEditBasicInfo}`} onStatusChange={() => void refetch()} />
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
                        {(data ?? []).map((app) => {
                            const { key, name, binding, workflow_requirements, resources } = app;
                            const panelEnabled = binding?.granted_capabilities.includes("panels.render");
                            const state = app.is_available === false ? "disabled" : (binding?.state ?? "unconfigured");
                            const workflowLabel = workflow_requirements ? "Configure workflow" : "App workflow contract pending";
                            return (
                                <article key={key} className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
                                    <h4 className="font-semibold">{name}</h4>
                                    <span className="self-start rounded-md bg-muted px-2 py-1 text-xs">
                                        {t(`project.settings.App state ${state}`)}
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
                                                                {t(`project.settings.App resource state ${state}`)} ·{" "}
                                                                {formatNumber(count, i18n.language)}
                                                            </span>
                                                        ))}
                                                    </div>
                                                ))
                                            )}
                                        </details>
                                    )}
                                    <p className="flex-1 text-sm text-muted-foreground">
                                        {app.description ?? t(`project.settings.App ${key} summary`, { defaultValue: "" })}
                                    </p>
                                    {app.inbound_connection_management && (
                                        <BoardSettingsAppConsent
                                            key={`${app.key}:${app.app_revision}:${app.binding?.revision}`}
                                            app={app}
                                            onRefresh={refetch}
                                        />
                                    )}
                                    {app.inbound_connection_management && (
                                        <Button size="sm" variant="outline" onClick={() => setConnections(app)}>
                                            {t("project.settings.Manage inbound connections")}
                                        </Button>
                                    )}
                                    {!app.panel && !app.inbound_connection_management && (
                                        <p className="text-xs text-muted-foreground">{t("project.settings.App connection setup pending")}</p>
                                    )}
                                    {(workflow_requirements || !app.panel) && (
                                        <>
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                disabled={pending || app.is_available === false || !workflow_requirements}
                                                onClick={() => setSelected(app)}
                                            >
                                                {t(`project.settings.${workflowLabel}`)}
                                            </Button>
                                        </>
                                    )}
                                    {app.panel &&
                                        app.capabilities.includes("panels.render") &&
                                        (panelTarget === key ? (
                                            <div className="flex flex-col gap-2 rounded-md border p-2">
                                                <p className="text-sm">{t("project.settings.App panel consent help", { name: app.panel.name })}</p>
                                                {app.capabilities.includes("signals.read") && (
                                                    <Checkbox
                                                        checked={readSignals}
                                                        onCheckedChange={(checked) => setReadSignals(checked === true)}
                                                        disabled={pending || !canEditBasicInfo}
                                                        label={t("project.settings.Allow App signal reads")}
                                                        description={t("project.settings.App signal read consent help")}
                                                    />
                                                )}
                                                <Button
                                                    size="sm"
                                                    disabled={pending || !canEditBasicInfo || !app.app_revision}
                                                    onClick={() => void setPanel(app, true)}
                                                >
                                                    {t("project.settings.Confirm App panel")}
                                                </Button>
                                                <Button size="sm" variant="ghost" disabled={pending} onClick={() => setPanelTarget(null)}>
                                                    {t("common.Cancel")}
                                                </Button>
                                            </div>
                                        ) : (
                                            <Button
                                                size="sm"
                                                variant="outline"
                                                disabled={pending || !canEditBasicInfo || !app.app_revision}
                                                onClick={() => {
                                                    if (panelEnabled) void setPanel(app, false);
                                                    else {
                                                        setReadSignals(false);
                                                        setPanelTarget(key);
                                                    }
                                                }}
                                            >
                                                {t(`project.settings.${panelEnabled ? "Disable App panel" : "Review App panel"}`)}
                                            </Button>
                                        ))}
                                    {binding &&
                                        binding.state !== "disabled" &&
                                        (disableTarget === key ? (
                                            <div className="flex flex-col gap-2">
                                                <p className="text-xs">{t("project.settings.Disable App help")}</p>
                                                <Button
                                                    size="sm"
                                                    variant="outline"
                                                    disabled={!canEditBasicInfo || pending}
                                                    onClick={() => void disable(app)}
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
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}
