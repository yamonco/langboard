import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import Select from "@/components/base/Select";
import Toast from "@/components/base/Toast";
import {
    IProjectTemplate,
    useGetProjectTemplates,
    useSetDefaultProjectTemplate,
} from "@/controllers/api/settings/projectTemplates/useProjectTemplates";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

function ProjectTemplatesPage() {
    const [t] = useTranslation();
    const { setPageAliasRef } = usePageHeader();
    const [templates, setTemplates] = useState<IProjectTemplate[]>([]);
    const [selected, setSelected] = useState<string>();
    const { mutateAsync: getTemplates } = useGetProjectTemplates({ interceptToast: true });
    const { mutateAsync: setDefault, isPending } = useSetDefaultProjectTemplate({ interceptToast: true });

    useEffect(() => {
        setPageAliasRef.current(t("settings.Project templates"));
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

    return (
        <Flex direction="col" gap="4">
            <Box textSize="3xl" weight="semibold">
                {t("settings.Project templates")}
            </Box>
            <Box className="text-muted-foreground">{t("settings.New projects use this template when no template is specified.")}</Box>
            <Flex gap="2" items="end" maxW="xl">
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
        </Flex>
    );
}

export default ProjectTemplatesPage;
