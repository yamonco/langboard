import { useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import BoardSettingsAppWorkflow from "./BoardSettingsAppWorkflow";

const starters = ["github", "glitchtip", "dokploy"] as const;
const names = { github: "GitHub", glitchtip: "GlitchTip", dokploy: "Dokploy" };
export default function BoardSettingsApps() {
    const [t] = useTranslation();
    const [dirty, setDirty] = useState(false);
    const [selected, setSelected] = useState<"github" | "glitchtip" | null>(null);
    return (
        <div className="flex w-full flex-col gap-4 py-4">
            {selected ? (
                <>
                    <Button size="sm" variant="outline" className="self-start" disabled={dirty} onClick={() => setSelected(null)}>
                        {t("project.settings.Back to App Store")}
                    </Button>
                    <h3 className="text-base font-semibold">{names[selected]}</h3>
                    <BoardSettingsAppWorkflow key={selected} appKey={selected} onDirtyChange={setDirty} />
                </>
            ) : (
                <>
                    <h3 className="text-base font-semibold">{t("project.settings.App Store")}</h3>
                    <p className="text-sm text-muted-foreground">{t("project.settings.App Store help")}</p>
                    <div className="grid gap-3 sm:grid-cols-3">
                        {starters.map((key) => (
                            <article key={key} className="flex min-w-0 flex-col gap-3 rounded-lg border p-4">
                                <h4 className="font-semibold">{names[key]}</h4>
                                <p className="flex-1 text-sm text-muted-foreground">{t(`project.settings.App ${key} summary`)}</p>
                                <p className="text-xs text-muted-foreground">{t("project.settings.App connection setup pending")}</p>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    disabled={key === "dokploy"}
                                    onClick={() => key !== "dokploy" && setSelected(key)}
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
