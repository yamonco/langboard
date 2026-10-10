import { formatNumber } from "@/core/utils/LocaleFormat";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import PillList from "@/components/base/PillList";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useDeleteApiComfortTool from "@/controllers/api/settings/schemas/useDeleteApiComfortTool";
import type { ApiComfortToolModel } from "@/core/models";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { useTranslation } from "react-i18next";

interface IApiComfortToolListItemProps {
    canDelete: bool;
    canUpdate: bool;
    comfortTool: ApiComfortToolModel.TModel;
    comfortToolName: string;
    deletingName?: string;
    isValidating: bool;
    onDeleted: (comfortToolName: string) => void;
    onEdit: (comfortToolName: string, comfortTool: ApiComfortToolModel.TModel) => void;
    setDeletingName: (comfortToolName?: string) => void;
}

function ApiComfortToolListItem({
    canDelete,
    canUpdate,
    comfortTool,
    comfortToolName,
    deletingName,
    isValidating,
    onDeleted,
    onEdit,
    setDeletingName,
}: IApiComfortToolListItemProps) {
    const [t, i18n] = useTranslation();
    const { setIsValidating } = useAppSetting();
    const { mutateAsync: deleteApiComfortToolMutateAsync } = useDeleteApiComfortTool(comfortTool, { interceptToast: true });
    const label = comfortTool.useField("label");
    const description = comfortTool.useField("description");
    const apiNames = comfortTool.useField("api_names");
    const isDefault = comfortTool.useField("is_default");
    const deleteComfortTool = async () => {
        if (isValidating || !canDelete || isDefault) {
            return;
        }

        setIsValidating(true);
        try {
            await deleteApiComfortToolMutateAsync({});
            onDeleted(comfortToolName);
            Toast.Add.success(t("successes.API comfort tool deleted successfully."));
        } finally {
            setIsValidating(false);
        }
    };

    return (
        <PillList.ItemRoot size="sm" className="max-sm:flex-col items-start gap-3">
            <PillList.ItemTitle className="min-w-0 flex-col items-start">
                <Flex justify="between" gap="3" className="max-sm:flex-col w-full">
                    <Box className="min-w-0">
                        <Box weight="semibold" className="truncate">
                            {label}
                        </Box>
                        <Box textSize="sm" className="break-all text-muted-foreground">
                            {comfortToolName}
                        </Box>
                    </Box>
                    <Box textSize="sm" className="whitespace-nowrap text-muted-foreground">
                        {t("settings.Selected base tools")}: {formatNumber(apiNames.length, i18n.language)}
                    </Box>
                </Flex>
                <Box mt="2" textSize="sm" className="text-muted-foreground">
                    {description}
                </Box>
                <Flex wrap gap="1.5" mt="3">
                    {apiNames.map((apiName) => (
                        <Box key={`api-comfort-tool-${comfortToolName}-${apiName}`} rounded className="bg-muted px-2 py-1 text-xs">
                            {apiName}
                        </Box>
                    ))}
                </Flex>
            </PillList.ItemTitle>
            <PillList.ItemContent>
                <Flex items="center" gap="1">
                    <Button
                        variant="outline"
                        size="icon-sm"
                        title={t("common.Edit")}
                        titleSide="bottom"
                        disabled={isValidating || !canUpdate || isDefault}
                        onClick={() => onEdit(comfortToolName, comfortTool)}
                    >
                        <IconComponent icon="pencil" size="4" />
                    </Button>
                    <Popover.Root
                        open={deletingName === comfortToolName}
                        onOpenChange={(open) => setDeletingName(open ? comfortToolName : undefined)}
                    >
                        <Popover.Trigger asChild>
                            <Button
                                variant="destructive"
                                size="icon-sm"
                                title={t("common.Delete")}
                                titleSide="bottom"
                                disabled={isValidating || !canDelete || isDefault}
                            >
                                <IconComponent icon="trash-2" size="4" />
                            </Button>
                        </Popover.Trigger>
                        <Popover.Content align="end">
                            <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                                {t("ask.Are you sure you want to delete this API comfort tool?")}
                            </Box>
                            <Flex items="center" justify="end" gap="1" mt="2">
                                <Button
                                    type="button"
                                    variant="secondary"
                                    size="sm"
                                    disabled={isValidating}
                                    onClick={() => setDeletingName(undefined)}
                                >
                                    {t("common.Cancel")}
                                </Button>
                                <SubmitButton type="button" variant="destructive" size="sm" onClick={deleteComfortTool} isValidating={isValidating}>
                                    {t("common.Delete")}
                                </SubmitButton>
                            </Flex>
                        </Popover.Content>
                    </Popover.Root>
                </Flex>
            </PillList.ItemContent>
        </PillList.ItemRoot>
    );
}

export default ApiComfortToolListItem;
