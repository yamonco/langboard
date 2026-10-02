import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Dialog from "@/components/base/Dialog";
import Button from "@/components/base/Button";
import Input from "@/components/base/Input";
import ColorPicker from "@/components/base/ColorPicker";
import Textarea from "@/components/base/Textarea";
import Sheet from "@/components/base/Sheet";
import Toast from "@/components/base/Toast";
import { AuthUser } from "@/core/models";
import { SettingRole } from "@/core/models/roles";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { IWorkflowStage, TWorkflowInput, useWorkflowStages } from "@/controllers/api/settings/workflowStages/useWorkflowStages";

const LANGUAGES: Record<string, string> = { en: "English", ko: "한국어", ja: "日本語", zh: "中文" };
const blank = (): TWorkflowInput => ({
    key: "",
    name: "",
    description: "",
    color: "#64748B",
    order: 0,
    counts_as_completed: false,
    active_queue_policy: "conditional",
    overdue_policy: "normal",
    entry_effects: [],
    translations: Object.fromEntries(Object.keys(LANGUAGES).map((key) => [key, { name: "", description: "" }])),
});

export default function WorkflowStagesPage({ currentUser }: { currentUser: AuthUser.TModel }) {
    const [t, i18n] = useTranslation();
    const { hasRoleAction } = useRoleActionFilter(currentUser.useField("setting_role_actions"));
    const { setPageAliasRef } = usePageHeader();
    const { load, save, deactivate } = useWorkflowStages();
    const [stages, setStages] = useState<IWorkflowStage[]>([]);
    const [draft, setDraft] = useState<TWorkflowInput>(blank);
    const [opened, setOpened] = useState(false);
    const [pickerContainer, setPickerContainer] = useState<HTMLDivElement | null>(null);
    const [dirty, setDirty] = useState(false);
    const [confirmation, setConfirmation] = useState<{ kind: "deactivate" | "close" } | { kind: "select"; stage?: IWorkflowStage } | null>(null);
    const [error, setError] = useState(false);
    const [language, setLanguage] = useState("en");
    const [newLanguage, setNewLanguage] = useState("");
    const busy = save.isPending || deactivate.isPending;
    const canSave = hasRoleAction(draft.uid ? SettingRole.EAction.WorkflowStageUpdate : SettingRole.EAction.WorkflowStageCreate);
    const reload = async () => {
        setError(false);
        try {
            setStages(await load.mutateAsync({}));
        } catch {
            setError(true);
        }
    };
    useEffect(() => {
        setPageAliasRef.current(t("settings.Workflow stages"));
        void reload();
    }, []);
    const applySelection = (stage?: IWorkflowStage) => {
        const { uid, key, name, description, color, order, counts_as_completed, active_queue_policy, overdue_policy, entry_effects, translations } =
            stage ?? { ...blank(), uid: undefined };
        setDraft({
            uid,
            key,
            name,
            description,
            color,
            order,
            counts_as_completed,
            active_queue_policy,
            overdue_policy,
            entry_effects: [...entry_effects],
            translations: { ...blank().translations, ...translations, en: { name, description } },
        });
        setLanguage("en");
        setDirty(false);
        setOpened(true);
    };
    const select = (stage?: IWorkflowStage) => {
        if (dirty) setConfirmation({ kind: "select", stage });
        else applySelection(stage);
    };
    const edit = (fields: Partial<TWorkflowInput>) => {
        setDraft((item) => ({ ...item, ...fields }));
        setDirty(true);
    };
    const editText = (field: "name" | "description", value: string) => {
        if (language === "en") edit({ [field]: value });
        else edit({ translations: { ...draft.translations, [language]: { ...draft.translations[language], [field]: value } } });
    };
    const replace = (stage: IWorkflowStage) =>
        setStages((items) =>
            [...items.filter((item) => item.uid !== stage.uid), stage].sort((a, b) => a.order - b.order || a.key.localeCompare(b.key))
        );
    const submit = async () => {
        if (!canSave || busy) return;
        try {
            const stage = await save.mutateAsync(draft);
            replace(stage);
            const { is_active: _, is_builtin: __, used_column_count: ___, ...input } = stage;
            setDraft(input);
            setDirty(false);
            Toast.Add.success(t("settings.Workflow stage saved"));
        } catch {
            Toast.Add.error(t("errors.Internal server error"));
        }
    };
    const disable = async () => {
        if (!draft.uid || busy || !hasRoleAction(SettingRole.EAction.WorkflowStageDeactivate)) return;
        try {
            replace(await deactivate.mutateAsync(draft.uid));
            setDirty(false);
            setOpened(false);
        } catch {
            Toast.Add.error(t("errors.Internal server error"));
        }
    };
    const text = language === "en" ? draft : draft.translations[language];
    const locale = i18n.language.split("-")[0];
    const selected = stages.find((stage) => stage.uid === draft.uid);
    return (
        <section className="space-y-5">
            <header className="flex flex-wrap items-center justify-between gap-3">
                <div>
                    <h1 className="text-2xl font-semibold">{t("settings.Workflow stages")}</h1>
                    <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                        {t("settings.Shared workflow meaning, independent of column names.")}
                    </p>
                </div>
                {hasRoleAction(SettingRole.EAction.WorkflowStageCreate) && (
                    <Button variant="outline" onClick={() => select()}>
                        {t("settings.New stage")}
                    </Button>
                )}
            </header>
            {error ? (
                <div role="alert" className="rounded-xl border p-4">
                    <p>{t("settings.Could not load workflow stages")}</p>
                    <Button variant="outline" onClick={() => void reload()}>
                        {t("common.Retry")}
                    </Button>
                </div>
            ) : load.isPending ? (
                <p>{t("common.Loading...")}</p>
            ) : (
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {stages.map((stage) => (
                        <button
                            key={stage.uid}
                            onClick={() => select(stage)}
                            className="rounded-xl border bg-card p-4 text-left transition-colors hover:bg-muted/40"
                        >
                            <div className="flex items-center gap-2">
                                <span className="size-3 shrink-0 rounded-full" style={{ backgroundColor: stage.color }} />
                                <span className="font-medium">{stage.translations[locale]?.name || stage.name}</span>
                                <span className="ml-auto text-xs text-muted-foreground">
                                    {stage.is_active ? t("settings.Active") : t("settings.Inactive")}
                                </span>
                            </div>
                            <p className="mt-1 font-mono text-xs text-muted-foreground">{stage.key}</p>
                            <p className="mt-1 text-xs text-muted-foreground">
                                {t("settings.Columns using this stage")}: {stage.used_column_count ?? 0}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-1 text-xs text-muted-foreground">
                                {stage.counts_as_completed && <span className="rounded-full border px-2 py-0.5">{t("settings.Completed")}</span>}
                                <span className="rounded-full border px-2 py-0.5">{t(`settings.Queue ${stage.active_queue_policy}`)}</span>
                                {stage.overdue_policy === "suppress" && (
                                    <span className="rounded-full border px-2 py-0.5">{t("settings.Hide overdue")}</span>
                                )}
                                <span className="rounded-full border px-2 py-0.5">
                                    {t("settings.Entry effects")}: {stage.entry_effects.length}
                                </span>
                            </div>
                        </button>
                    ))}
                </div>
            )}
            <Sheet.Root
                open={opened}
                onOpenChange={(value) => {
                    if (busy) return;
                    if (!value && dirty) {
                        setConfirmation({ kind: "close" });
                        return;
                    }
                    setOpened(value);
                    if (!value) setDirty(false);
                }}
            >
                <Sheet.Content ref={setPickerContainer} side="right" className="w-full overflow-y-auto sm:max-w-xl">
                    <Sheet.Header>
                        <Sheet.Title>{draft.uid ? draft.name : t("settings.New stage")}</Sheet.Title>
                        <Sheet.Description>{t("settings.Machine keys remain fixed after creation.")}</Sheet.Description>
                    </Sheet.Header>
                    <form
                        className="mt-5 space-y-4"
                        onSubmit={(event) => {
                            event.preventDefault();
                            void submit();
                        }}
                    >
                        <label className="block space-y-1 text-sm">
                            {t("settings.Machine key")}
                            <Input
                                value={draft.key}
                                required
                                pattern="[a-z][a-z0-9_]{0,63}"
                                disabled={!!draft.uid || !canSave || busy}
                                onChange={(event) => edit({ key: event.target.value })}
                            />
                        </label>
                        <div className="flex flex-wrap gap-1" role="group" aria-label={t("settings.Languages")}>
                            {Object.keys(draft.translations).map((key) => (
                                <Button
                                    type="button"
                                    size="sm"
                                    variant={language === key ? "secondary" : "ghost"}
                                    key={key}
                                    onClick={() => setLanguage(key)}
                                >
                                    {LANGUAGES[key] ?? key}
                                </Button>
                            ))}
                        </div>
                        <label className="block space-y-1 text-sm">
                            {t("settings.Stage name")}
                            <Input
                                value={text?.name ?? ""}
                                required={language === "en"}
                                maxLength={100}
                                disabled={!canSave || busy}
                                onChange={(event) => editText("name", event.target.value)}
                            />
                        </label>
                        <label className="block space-y-1 text-sm">
                            {t("settings.Stage description")}
                            <Textarea
                                value={text?.description ?? ""}
                                maxLength={4000}
                                rows={3}
                                disabled={!canSave || busy}
                                onChange={(event) => editText("description", event.target.value)}
                            />
                        </label>
                        <div className="flex gap-2">
                            <Input
                                aria-label={t("settings.Language code")}
                                placeholder="fr"
                                value={newLanguage}
                                onChange={(event) => setNewLanguage(event.target.value)}
                                disabled={!canSave || busy}
                            />
                            <Button
                                type="button"
                                variant="outline"
                                disabled={
                                    !canSave ||
                                    busy ||
                                    Object.keys(draft.translations).length >= 30 ||
                                    !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(newLanguage) ||
                                    !!draft.translations[newLanguage]
                                }
                                onClick={() => {
                                    edit({ translations: { ...draft.translations, [newLanguage]: { name: "", description: "" } } });
                                    setLanguage(newLanguage);
                                    setNewLanguage("");
                                }}
                            >
                                {t("settings.Add language")}
                            </Button>
                        </div>
                        <p className="text-xs text-muted-foreground">{t("settings.English is the default and fallback language.")}</p>
                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-1 text-sm">
                                <span>{t("settings.Color")}</span>
                                <div className="flex items-center gap-2">
                                    <ColorPicker
                                        portalContainer={pickerContainer}
                                        type="button"
                                        aria-label={t("settings.Color")}
                                        value={/^#[0-9a-fA-F]{6}$/.test(draft.color) ? draft.color : "#64748B"}
                                        isValidating={!canSave || busy}
                                        popoverContentAlign="start"
                                        onSave={(color, close) => {
                                            if (!/^#[0-9a-fA-F]{6}$/.test(color)) return;
                                            edit({ color });
                                            close();
                                        }}
                                    />
                                    <Input
                                        aria-label={t("settings.Color hex code")}
                                        value={draft.color}
                                        maxLength={7}
                                        pattern="#[0-9a-fA-F]{6}"
                                        disabled={!canSave || busy}
                                        className="w-28 font-mono text-xs uppercase"
                                        onChange={(event) => edit({ color: event.target.value })}
                                    />
                                </div>
                            </div>
                            <label className="space-y-1 text-sm">
                                {t("settings.Order")}
                                <Input
                                    type="number"
                                    min={0}
                                    max={100000}
                                    value={draft.order}
                                    disabled={!canSave || busy}
                                    onChange={(event) => edit({ order: Number(event.target.value) })}
                                />
                            </label>
                        </div>
                        <fieldset disabled={!canSave || busy} className="space-y-3 rounded-xl border p-3">
                            <legend className="px-1 text-sm font-medium">{t("settings.Stage policy")}</legend>
                            <label className="flex items-center gap-2 text-sm">
                                <input
                                    type="checkbox"
                                    checked={draft.counts_as_completed}
                                    onChange={(event) => edit({ counts_as_completed: event.target.checked })}
                                />
                                {t("settings.Count as completed")}
                            </label>
                            <label className="block space-y-1 text-sm">
                                {t("settings.Active queue")}
                                <select
                                    aria-label={t("settings.Active queue")}
                                    className="h-9 w-full rounded-md border bg-background px-2"
                                    value={draft.active_queue_policy}
                                    onChange={(event) => edit({ active_queue_policy: event.target.value as TWorkflowInput["active_queue_policy"] })}
                                >
                                    {["include", "exclude", "conditional"].map((value) => (
                                        <option key={value} value={value}>
                                            {t(`settings.Queue ${value}`)}
                                        </option>
                                    ))}
                                </select>
                            </label>
                            <label className="flex items-center gap-2 text-sm">
                                <input
                                    type="checkbox"
                                    checked={draft.overdue_policy === "suppress"}
                                    onChange={(event) => edit({ overdue_policy: event.target.checked ? "suppress" : "normal" })}
                                />
                                {t("settings.Hide overdue")}
                            </label>
                        </fieldset>
                        <fieldset disabled={!canSave || busy} className="space-y-2 rounded-xl border p-3">
                            <legend className="px-1 text-sm font-medium">{t("settings.Entry effects")}</legend>
                            {[
                                ["complete_checkitems", "Complete unchecked items"],
                                ["stop_running_timers", "Stop running timers"],
                            ].map(([key, label]) => (
                                <label key={key} className="flex items-center gap-2 text-sm">
                                    <input
                                        type="checkbox"
                                        checked={draft.entry_effects.includes(key)}
                                        onChange={(event) =>
                                            edit({
                                                entry_effects: event.target.checked
                                                    ? [...draft.entry_effects, key]
                                                    : draft.entry_effects.filter((effect) => effect !== key),
                                            })
                                        }
                                    />
                                    {t(`settings.${label}`)}
                                </label>
                            ))}
                            <p className="text-xs text-muted-foreground">{t("settings.Saving does not replay effects on existing cards.")}</p>
                        </fieldset>
                        <div className="flex flex-wrap justify-between gap-2 border-t pt-4">
                            {selected?.is_active && hasRoleAction(SettingRole.EAction.WorkflowStageDeactivate) && (
                                <Button type="button" variant="outline" disabled={busy} onClick={() => setConfirmation({ kind: "deactivate" })}>
                                    {t("settings.Deactivate")}
                                </Button>
                            )}
                            <Button type="submit" disabled={!canSave || busy || !dirty}>
                                {busy ? t("common.Loading...") : t("common.Save")}
                            </Button>
                        </div>
                    </form>
                </Sheet.Content>
            </Sheet.Root>
            <Dialog.Root
                open={confirmation !== null}
                onOpenChange={(value) => {
                    if (!value) setConfirmation(null);
                }}
            >
                <Dialog.Content>
                    <Dialog.Header>
                        <Dialog.Title>
                            {confirmation?.kind === "deactivate" ? t("settings.Deactivate") : t("settings.Discard unsaved changes?")}
                        </Dialog.Title>
                        <Dialog.Description>
                            {confirmation?.kind === "deactivate"
                                ? t("settings.Deactivate this stage? Existing bindings are preserved.")
                                : t("settings.Discard unsaved changes?")}
                        </Dialog.Description>
                    </Dialog.Header>
                    <Dialog.Footer>
                        <Button variant="outline" onClick={() => setConfirmation(null)}>
                            {t("common.Cancel")}
                        </Button>
                        <Button
                            onClick={() => {
                                const action = confirmation;
                                setConfirmation(null);
                                if (action?.kind === "deactivate") void disable();
                                else if (action?.kind === "select") applySelection(action.stage);
                                else if (action?.kind === "close") {
                                    setOpened(false);
                                    setDirty(false);
                                }
                            }}
                        >
                            {confirmation?.kind === "deactivate" ? t("settings.Deactivate") : t("settings.Discard changes")}
                        </Button>
                    </Dialog.Footer>
                </Dialog.Content>
            </Dialog.Root>
        </section>
    );
}
