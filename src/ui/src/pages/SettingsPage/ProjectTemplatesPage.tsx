import Input from "@/components/base/Input";
import Textarea from "@/components/base/Textarea";
import { useWorkflowStages } from "@/controllers/api/settings/workflowStages/useWorkflowStages";
import { metadataDisplay } from "@/core/utils/MetadataDisplay";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Select from "@/components/base/Select";
import Toast from "@/components/base/Toast";
import {
    IProjectTemplate,
    ITemplateColumn,
    useSaveProjectTemplate,
    useGetProjectTemplates,
    useSetDefaultProjectTemplate,
} from "@/controllers/api/settings/projectTemplates/useProjectTemplates";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

function ProjectTemplatesPage() {
    const [t, i18n] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const [templates, setTemplates] = useState<IProjectTemplate[]>([]);
    const [selected, setSelected] = useState<string>();
    const { mutateAsync: getTemplates } = useGetProjectTemplates({ interceptToast: true });
    const { mutateAsync: setDefault, isPending } = useSetDefaultProjectTemplate({ interceptToast: true });
    const { mutateAsync: saveTemplate, isPending: isSaving } = useSaveProjectTemplate();
    const { load } = useWorkflowStages();
    const [stages, setStages] = useState<Awaited<ReturnType<typeof load.mutateAsync>>>([]);
    const [draft, setDraft] = useState<{ uid?: string; name: string; columns: ITemplateColumn[] } | null>(null);
    const [language, setLanguage] = useState("en");
    const [newLanguage, setNewLanguage] = useState("");
    const [error, setError] = useState(false);
    const selectedTemplate = templates.find((template) => template.name === selected);

    useEffect(() => {
        setPageAliasRef.current(t("settings.Project templates"));
        load.mutateAsync({})
            .then(setStages)
            .catch(() => setError(true));
        getTemplates({})
            .then((items) => {
                setTemplates(items);
                setSelected(items.find((item) => item.is_default)?.name ?? items[0]?.name);
            })
            .catch(() => Toast.Add.error(t("errors.Internal server error")));
    }, []);

    const save = () => {
        if (!selected) return;
        const promise = setDefault({ template_name: selected });
        Toast.Add.promise(promise, {
            loading: t("common.Saving..."),
            error: () => t("errors.Internal server error"),
            success: (updated) => {
                setTemplates((items) => items.map((item) => ({ ...item, is_default: item.name === updated.name })));
                return t("successes.Default project template updated.");
            },
        });
    };

    const edit = (template?: IProjectTemplate) => {
        setError(false);
        setLanguage("en");
        setNewLanguage("");
        setDraft(
            template
                ? {
                      uid: template.uid,
                      name: template.name,
                      columns: (
                          template.column_definitions ??
                          template.columns.map((name, index) => ({
                              name,
                              description: template.column_descriptions?.[index] ?? "",
                              workflow_stage: null,
                              translations: {},
                          }))
                      ).map((column) => ({ ...column, translations: { ...column.translations } })),
                  }
                : { name: "", columns: [{ name: "", description: "", workflow_stage: null }] }
        );
    };
    const updateColumn = (index: number, fields: Partial<ITemplateColumn>) =>
        setDraft(
            (current) => current && { ...current, columns: current.columns.map((column, i) => (i === index ? { ...column, ...fields } : column)) }
        );
    const persist = async () => {
        if (!draft) return;
        try {
            const result = await saveTemplate(draft);
            setTemplates((items) => [...items.filter((item) => item.uid !== result.uid), result]);
            setSelected(result.name);
            setDraft(null);
            setError(false);
        } catch {
            setError(true);
        }
    };
    return (
        <Flex direction="col" gap="4">
            <Box textSize="3xl" weight="semibold">
                {t("settings.Project templates")}
            </Box>
            <Box className="text-muted-foreground">{t("settings.New projects use this template when no template is specified.")}</Box>
            <Flex gap="2" items="end" className="max-w-xl">
                <Box className="grow">
                    <Select.Root value={selected} onValueChange={setSelected}>
                        <Select.Trigger>
                            <Select.Value placeholder={t("settings.Select a template")} />
                        </Select.Trigger>
                        <Select.Content>
                            {templates.map((template) => (
                                <Select.Item key={template.uid} value={template.name}>
                                    {template.name} · {template.columns.join(" → ")}
                                </Select.Item>
                            ))}
                        </Select.Content>
                    </Select.Root>
                </Box>
                <Button disabled={!selected || isPending} onClick={save}>
                    {t("settings.Save default")}
                </Button>
            </Flex>
            <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => edit()}>
                    {t("settings.New template")}
                </Button>
                <Button variant="outline" disabled={!selectedTemplate} onClick={() => edit(selectedTemplate)}>
                    {t("common.Edit")}
                </Button>
            </div>
            {draft && (
                <form
                    className="space-y-4 rounded-xl border bg-card p-4"
                    onSubmit={(event) => {
                        event.preventDefault();
                        void persist();
                    }}
                >
                    <Input
                        aria-label={t("settings.Template name")}
                        value={draft.name}
                        maxLength={100}
                        disabled={templates.find((template) => template.uid === draft.uid)?.is_builtin}
                        onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                        required
                    />
                    <div className="flex flex-wrap gap-2">
                        {Array.from(
                            new Set(["en", "ko", "ja", "zh", ...draft.columns.flatMap((column) => Object.keys(column.translations ?? {}))])
                        ).map((code) => (
                            <Button key={code} type="button" variant={language === code ? "secondary" : "ghost"} onClick={() => setLanguage(code)}>
                                {code}
                            </Button>
                        ))}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <Input
                            className="max-w-40"
                            aria-label={t("settings.Language code")}
                            value={newLanguage}
                            onChange={(event) => setNewLanguage(event.target.value)}
                        />
                        <Button
                            type="button"
                            variant="outline"
                            disabled={
                                !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(newLanguage) ||
                                draft.columns.some((column) => !!column.translations?.[newLanguage]) ||
                                Object.keys(draft.columns[0].translations ?? {}).length >= 30
                            }
                            onClick={() => {
                                setDraft({
                                    ...draft,
                                    columns: draft.columns.map((column) => ({
                                        ...column,
                                        translations: { ...column.translations, [newLanguage]: { name: "", description: "" } },
                                    })),
                                });
                                setLanguage(newLanguage);
                                setNewLanguage("");
                            }}
                        >
                            {t("settings.Add language")}
                        </Button>
                    </div>
                    {draft.columns.map((column, index) => {
                        const display = language === "en" ? column : (column.translations?.[language] ?? { name: "", description: "" });
                        const updateText = (fields: { name?: string; description?: string }) =>
                            language === "en"
                                ? updateColumn(index, fields)
                                : updateColumn(index, { translations: { ...column.translations, [language]: { ...display, ...fields } } });
                        return (
                            <fieldset key={index} className="space-y-2 rounded-lg border p-3">
                                <Input
                                    aria-label={t("settings.Column name")}
                                    value={display.name}
                                    maxLength={100}
                                    required={language === "en"}
                                    onChange={(event) => updateText({ name: event.target.value })}
                                />
                                <Textarea
                                    aria-label={t("project.Column description")}
                                    value={display.description}
                                    maxLength={4096}
                                    onChange={(event) => updateText({ description: event.target.value })}
                                />
                                <select
                                    aria-label={t("common.Workflow stage")}
                                    className="w-full rounded border bg-background p-2"
                                    value={column.workflow_stage ?? ""}
                                    onChange={(event) => updateColumn(index, { workflow_stage: event.target.value || null })}
                                >
                                    <option value="">{t("board.Unclassified")}</option>
                                    {column.workflow_stage && !stages.some((stage) => stage.key === column.workflow_stage) && (
                                        <option value={column.workflow_stage}>{column.workflow_stage}</option>
                                    )}
                                    {stages.map((stage) => (
                                        <option key={stage.key} value={stage.key} disabled={!stage.is_active && stage.key !== column.workflow_stage}>
                                            {metadataDisplay(stage, stage.translations, i18n.language).name}
                                        </option>
                                    ))}
                                </select>
                                <div className="flex gap-2">
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        disabled={index === 0}
                                        onClick={() => {
                                            const columns = [...draft.columns];
                                            [columns[index - 1], columns[index]] = [columns[index], columns[index - 1]];
                                            setDraft({ ...draft, columns });
                                        }}
                                    >
                                        {t("settings.Move up")}
                                    </Button>
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        disabled={draft.columns.length === 1}
                                        onClick={() => setDraft({ ...draft, columns: draft.columns.filter((_, i) => i !== index) })}
                                    >
                                        {t("common.Delete")}
                                    </Button>
                                </div>
                            </fieldset>
                        );
                    })}
                    <Button
                        type="button"
                        variant="outline"
                        onClick={() => setDraft({ ...draft, columns: [...draft.columns, { name: "", description: "", workflow_stage: null }] })}
                    >
                        {t("settings.Add column")}
                    </Button>
                    {error && (
                        <p role="alert" className="text-sm text-destructive">
                            {t("errors.Internal server error")}
                        </p>
                    )}
                    <div className="flex justify-end gap-2">
                        <Button type="button" variant="ghost" disabled={isSaving} onClick={() => setDraft(null)}>
                            {t("common.Cancel")}
                        </Button>
                        <Button type="submit" disabled={isSaving}>
                            {t("common.Save")}
                        </Button>
                    </div>
                </form>
            )}
            <ol className="max-w-xl space-y-3">
                {selectedTemplate?.columns.map((name, index) => {
                    const definition = selectedTemplate.column_definitions?.[index];
                    const display = metadataDisplay(
                        { name, description: selectedTemplate.column_descriptions?.[index] ?? "" },
                        definition?.translations,
                        i18n.language
                    );
                    return (
                        <li key={`${index}-${name}`}>
                            <p className="font-medium">
                                {index + 1}. {display.name}
                            </p>
                            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
                                {display.description || t("project.No column description")}
                            </p>
                        </li>
                    );
                })}
            </ol>
        </Flex>
    );
}

export default ProjectTemplatesPage;
