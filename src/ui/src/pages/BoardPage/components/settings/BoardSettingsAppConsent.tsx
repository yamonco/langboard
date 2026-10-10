import Button from "@/components/base/Button";
import Checkbox from "@/components/base/Checkbox";
import type { CatalogApp } from "@/controllers/api/board/useBoardAppCatalog";
import { api } from "@/core/helpers/Api";
import { useBoardSettings } from "@/core/providers/BoardSettingsProvider";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export default function BoardSettingsAppConsent({ app, onRefresh }: { app: CatalogApp; onRefresh: () => Promise<{ isError: boolean }> }) {
    const [t] = useTranslation();
    const { project, canEditBasicInfo } = useBoardSettings();
    const [opened, setOpened] = useState(false);
    const [grants, setGrants] = useState(app.binding?.granted_capabilities ?? []);
    const [pending, setPending] = useState(false);
    const [failed, setFailed] = useState(false);
    const writing = useRef(false);
    const refresh = async () => {
        setPending(true);
        try {
            const result = await onRefresh();
            if (!result.isError) {
                setFailed(false);
                setOpened(false);
                setGrants(app.binding?.granted_capabilities ?? []);
            } else setFailed(true);
        } finally {
            setPending(false);
        }
    };
    const save = async () => {
        if (!app.binding || !app.app_revision || !canEditBasicInfo || pending || failed || writing.current) return;
        writing.current = true;
        setPending(true);
        try {
            await api.put(
                `/board/${project.uid}/settings/apps/${encodeURIComponent(app.key)}/consent`,
                {
                    app_revision: app.app_revision,
                    binding_uid: app.binding.uid,
                    expected_revision: app.binding.revision,
                    capabilities: grants,
                },
                { env: { interceptToast: true } as never }
            );
            setOpened(false);
            const result = await onRefresh();
            setFailed(result.isError);
        } catch {
            setFailed(true);
        } finally {
            writing.current = false;
            setPending(false);
        }
    };
    if (!app.binding) return <p className="text-xs text-muted-foreground">{t("project.settings.Prepare workflow before consent")}</p>;
    return (
        <div className="space-y-2">
            <Button variant="outline" size="sm" disabled={pending} onClick={() => setOpened(!opened)}>
                {t("project.settings.Review App permissions")}
            </Button>
            {opened && (
                <div className="space-y-3 rounded-md border p-3">
                    <p className="text-xs text-muted-foreground">{t("project.settings.App explicit permissions help")}</p>
                    {[...new Set([...app.capabilities, ...app.binding.granted_capabilities])].map((capability) => (
                        <Checkbox
                            key={capability}
                            label={capability}
                            checked={grants.includes(capability)}
                            disabled={
                                !canEditBasicInfo ||
                                pending ||
                                failed ||
                                app.is_available === false ||
                                (!app.capabilities.includes(capability) && !grants.includes(capability))
                            }
                            onCheckedChange={(checked) =>
                                setGrants((current) =>
                                    checked === true ? [...current, capability] : current.filter((value) => value !== capability)
                                )
                            }
                        />
                    ))}
                    {failed && (
                        <p role="alert" className="text-sm">
                            {t("project.settings.Inbound connection refresh required")}
                        </p>
                    )}
                    <div className="flex flex-wrap gap-2">
                        <Button
                            size="sm"
                            disabled={!canEditBasicInfo || pending || failed || (app.is_available === false && grants.length > 0)}
                            onClick={() => void save()}
                        >
                            {t("project.settings.Save reviewed permissions")}
                        </Button>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={!canEditBasicInfo || pending || failed}
                            onClick={() => {
                                setGrants([]);
                            }}
                        >
                            {t("project.settings.Clear App permissions")}
                        </Button>
                        <Button
                            variant="ghost"
                            size="sm"
                            disabled={pending}
                            onClick={() => {
                                void refresh();
                            }}
                        >
                            {t("project.settings.Back and refresh App permissions")}
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}
