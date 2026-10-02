import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Button from "@/components/base/Button";
import Input from "@/components/base/Input";
import ColorPicker from "@/components/base/ColorPicker";
import Textarea from "@/components/base/Textarea";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import { AuthUser } from "@/core/models";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { SettingRole } from "@/core/models/roles";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { IGlobalLabel, TGlobalLabelInput, useGetGlobalLabels, useSaveGlobalLabel } from "@/controllers/api/settings/globalLabels/useGlobalLabels";

const LANGUAGES: Record<string, string> = { en: "English", ko: "한국어", ja: "日本語", zh: "中文" };
const blank = (): TGlobalLabelInput => ({
    name: "",
    color: "#4A90E2",
    description: "",
    emoji: "",
    translations: Object.fromEntries(Object.keys(LANGUAGES).map((key) => [key, { name: "", description: "" }])),
});

export default function GlobalLabelsPage({ currentUser }: { currentUser: AuthUser.TModel }) {
    const [t, i18n] = useTranslation();
    const actions = currentUser.useField("setting_role_actions");
    const { hasRoleAction } = useRoleActionFilter(actions);
    const { setPageAliasRef } = usePageHeader();
    const [labels, setLabels] = useState<IGlobalLabel[]>([]);
    const [draft, setDraft] = useState<TGlobalLabelInput>(blank);
    const [language, setLanguage] = useState("en");
    const [newLanguage, setNewLanguage] = useState("");
    const [dirty, setDirty] = useState(false);
    const { mutateAsync: load, isPending: loading } = useGetGlobalLabels({ interceptToast: true });
    const { mutateAsync: save, isPending: saving } = useSaveGlobalLabel({ interceptToast: true });
    const canSave = hasRoleAction(draft.uid ? SettingRole.EAction.GlobalLabelUpdate : SettingRole.EAction.GlobalLabelCreate);
    useEffect(() => {
        setPageAliasRef.current(t("settings.Global labels"));
        let active = true;
        load({})
            .then((items) => {
                if (active) setLabels(items);
            })
            .catch(() => Toast.Add.error(t("errors.Internal server error")));
        return () => {
            active = false;
        };
    }, []);
    const select = (label?: IGlobalLabel) => {
        if (dirty && !window.confirm(t("settings.Discard unsaved changes?"))) return;
        setDraft(
            label
                ? {
                      ...label,
                      translations: { ...blank().translations, ...label.translations, en: { name: label.name, description: label.description } },
                  }
                : blank()
        );
        setDirty(false);
        setLanguage("en");
    };
    const text = language === "en" ? draft : draft.translations[language];
    const edit = (key: "name" | "description", value: string) => {
        setDraft((item) =>
            language === "en"
                ? { ...item, [key]: value }
                : { ...item, translations: { ...item.translations, [language]: { ...item.translations[language], [key]: value } } }
        );
        setDirty(true);
    };
    const submit = async () => {
        try {
            const updated = await save(draft);
            setLabels((items) => [...items.filter((item) => item.uid !== updated.uid), updated].sort((a, b) => a.name.localeCompare(b.name)));
            setDraft(updated);
            setDirty(false);
            Toast.Add.success(t("settings.Label saved"));
        } catch {
            Toast.Add.error(t("errors.Internal server error"));
        }
    };
    const locale = i18n.resolvedLanguage?.split("-")[0] ?? "en";
    return (
        <section className="space-y-5">
            <header className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-2xl font-semibold">{t("settings.Global labels")}</h1>
                    <p className="mt-1 text-sm text-muted-foreground">
                        {t("settings.Reusable labels for project templates. Existing project labels keep their own values.")}
                    </p>
                </div>
                {hasRoleAction(SettingRole.EAction.GlobalLabelCreate) && (
                    <Button variant="outline" onClick={() => select()}>
                        <IconComponent icon="plus" className="mr-2 size-4" />
                        {t("settings.New label")}
                    </Button>
                )}
            </header>
            <div className="grid gap-4 md:grid-cols-[minmax(180px,260px)_minmax(0,1fr)]">
                <nav aria-label={t("settings.Global labels")} className="max-h-[65vh] space-y-1 overflow-y-auto rounded-xl border bg-card p-2">
                    {loading ? (
                        <p className="p-3 text-sm text-muted-foreground">{t("common.Loading...")}</p>
                    ) : !labels.length ? (
                        <p className="p-3 text-sm text-muted-foreground">{t("settings.No global labels yet")}</p>
                    ) : (
                        labels.map((label) => (
                            <button
                                key={label.uid}
                                type="button"
                                aria-pressed={draft.uid === label.uid}
                                onClick={() => select(label)}
                                className={[
                                    "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-accent",
                                    draft.uid === label.uid ? "bg-accent" : "",
                                ].join(" ")}
                            >
                                <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: label.color }} />
                                <span className="truncate">
                                    {label.emoji && `${label.emoji} `}
                                    {label.translations[locale]?.name || label.name}
                                </span>
                            </button>
                        ))
                    )}
                </nav>
                <form
                    className="min-w-0 space-y-4 rounded-xl border bg-card p-5"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void submit();
                    }}
                >
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-full border px-3 py-1 text-sm" style={{ color: draft.color }}>
                            {draft.emoji && `${draft.emoji} `}
                            {text?.name || draft.name || t("settings.Label preview")}
                        </span>
                        <span className="text-xs text-muted-foreground">{t("settings.English is the default and fallback language.")}</span>
                    </div>
                    <div className="flex flex-wrap gap-1" role="group" aria-label={t("settings.Languages")}>
                        {Object.keys(draft.translations).map((key) => (
                            <Button
                                key={key}
                                type="button"
                                size="sm"
                                variant={language === key ? "secondary" : "ghost"}
                                onClick={() => setLanguage(key)}
                            >
                                {LANGUAGES[key] ?? key}
                            </Button>
                        ))}
                    </div>
                    <label className="block space-y-1 text-sm">
                        <span>{t("settings.Label name")}</span>
                        <Input
                            value={text?.name ?? ""}
                            required={language === "en"}
                            maxLength={100}
                            disabled={!canSave}
                            onChange={(e) => edit("name", e.target.value)}
                        />
                    </label>
                    <label className="block space-y-1 text-sm">
                        <span>{t("settings.Label description")}</span>
                        <Textarea
                            aria-label={t("settings.Label description")}
                            value={text?.description ?? ""}
                            maxLength={4000}
                            rows={4}
                            disabled={!canSave}
                            onChange={(e) => edit("description", e.target.value)}
                        />
                    </label>
                    <label className="block space-y-1.5 text-sm">
                        <span>{t("settings.Emoji (optional)")}</span>
                        <Input
                            aria-label={t("settings.Emoji (optional)")}
                            value={draft.emoji ?? ""}
                            maxLength={32}
                            placeholder="🏷️"
                            disabled={!canSave}
                            className="w-24 text-center text-lg"
                            onChange={(event) => {
                                setDraft((item) => ({ ...item, emoji: event.target.value }));
                                setDirty(true);
                            }}
                        />
                    </label>
                    <label className="flex items-center gap-3 text-sm">
                        <span>{t("settings.Color")}</span>
                        <ColorPicker
                            type="button"
                            aria-label={t("settings.Color")}
                            value={/^#[0-9a-fA-F]{6}$/.test(draft.color) ? draft.color : "#4A90E2"}
                            isValidating={!canSave || saving}
                            popoverContentAlign="start"
                            onSave={(color, close) => {
                                if (!/^#[0-9a-fA-F]{6}$/.test(color)) return;
                                setDraft((item) => ({ ...item, color }));
                                setDirty(true);
                                close();
                            }}
                        />
                        <Input
                            aria-label={t("settings.Color hex code")}
                            value={draft.color}
                            maxLength={7}
                            disabled={!canSave}
                            className="w-28 font-mono text-xs uppercase"
                            onChange={(event) => {
                                setDraft((item) => ({ ...item, color: event.target.value }));
                                setDirty(true);
                            }}
                        />
                    </label>
                    {canSave && (
                        <div className="flex flex-wrap gap-2">
                            <Input
                                aria-label={t("settings.Language code")}
                                placeholder="fr, de, zh-TW…"
                                value={newLanguage}
                                onChange={(e) => setNewLanguage(e.target.value)}
                                className="max-w-44"
                            />
                            <Button
                                type="button"
                                variant="outline"
                                disabled={
                                    !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(newLanguage) ||
                                    !!draft.translations[newLanguage] ||
                                    Object.keys(draft.translations).length >= 30
                                }
                                onClick={() => {
                                    setDraft((item) => ({
                                        ...item,
                                        translations: { ...item.translations, [newLanguage]: { name: "", description: "" } },
                                    }));
                                    setLanguage(newLanguage);
                                    setNewLanguage("");
                                    setDirty(true);
                                }}
                            >
                                {t("settings.Add language")}
                            </Button>
                        </div>
                    )}
                    <div className="flex justify-end border-t pt-4">
                        <Button type="submit" disabled={!canSave || saving || !draft.name.trim() || !/^#[0-9a-fA-F]{6}$/.test(draft.color) || !dirty}>
                            {saving ? t("common.Saving...") : t("common.Save")}
                        </Button>
                    </div>
                </form>
            </div>
        </section>
    );
}
