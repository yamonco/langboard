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

function ProjectTemplatesPage() {
    const { setPageAliasRef } = usePageHeader();
    const [templates, setTemplates] = useState<IProjectTemplate[]>([]);
    const [selected, setSelected] = useState("");
    const { mutateAsync: getTemplates } = useGetProjectTemplates();
    const { mutateAsync: setDefault, isPending } = useSetDefaultProjectTemplate();

    useEffect(() => {
        setPageAliasRef.current("Project templates");
        getTemplates({}).then((items) => {
            setTemplates(items);
            setSelected(items.find((item) => item.is_default)?.name ?? items[0]?.name ?? "");
        });
    }, []);

    const save = async () => {
        const updated = await setDefault({ template_name: selected });
        setTemplates((items) => items.map((item) => ({ ...item, is_default: item.name === updated.name })));
        Toast.Add.success("Default project template updated.");
    };

    return (
        <Flex direction="col" gap="4">
            <Box textSize="3xl" weight="semibold">
                Project templates
            </Box>
            <Box className="text-muted-foreground">New projects use this template when no template is specified.</Box>
            <Flex gap="2" items="end" maxW="xl">
                <Box className="grow">
                    <Select.Root value={selected} onValueChange={setSelected}>
                        <Select.Trigger>
                            <Select.Value placeholder="Select a template" />
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
                    Save default
                </Button>
            </Flex>
        </Flex>
    );
}

export default ProjectTemplatesPage;
