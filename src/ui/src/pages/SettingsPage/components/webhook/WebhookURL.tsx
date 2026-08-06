import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Table from "@/components/base/Table";
import Toast from "@/components/base/Toast";
import Collaborative from "@/components/Collaborative";
import useUpdateWebhook from "@/controllers/api/settings/webhooks/useUpdateWebhook";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useChangeEditMode from "@/core/hooks/useChangeEditMode";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { ModelRegistry } from "@/core/models/ModelRegistry";
import { SettingRole } from "@/core/models/roles";
import { ROUTES } from "@/core/routing/constants";
import { cn } from "@/core/utils/ComponentUtils";
import { EEditorCollaborationType } from "@langboard/core/constants";
import { EHttpStatus } from "@langboard/core/enums";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

function WebhookURL() {
    const [t] = useTranslation();
    const { model: webhook } = ModelRegistry.WebhookModel.useContext();
    const navigate = usePageNavigateRef();
    const { currentUser } = useAppSetting();
    const settingRoleActions = currentUser.useField("setting_role_actions");
    const { hasRoleAction } = useRoleActionFilter(settingRoleActions);
    const canUpdateWebhook = hasRoleAction(SettingRole.EAction.WebhookUpdate);
    const urlValue = webhook.useField("url");
    const [draftURL, setDraftURL] = useState(urlValue);
    const editorName = `${webhook.uid}-webhook-url`;
    const { mutateAsync } = useUpdateWebhook(webhook, { interceptToast: true });
    const resetCollaborativeURLRef = useRef<((value: string) => void) | null>(null);

    const { valueRef, isEditing, setIsEditing, changeMode } = useChangeEditMode({
        canEdit: () => canUpdateWebhook,
        valueType: "input",
        editorName,
        save: (_, endCallback) => {
            endCallback();
        },
        originalValue: urlValue,
    });
    const startEdit = () => {
        setDraftURL(urlValue);
        changeMode("edit");
    };
    const saveEdit = () => {
        const nextURL = (valueRef.current?.value ?? draftURL).trim();
        if (!nextURL || nextURL === urlValue.trim()) {
            setIsEditing(false);
            return;
        }

        const promise = mutateAsync({
            url: nextURL,
        });

        Toast.Add.promise(promise, {
            loading: t("common.Changing..."),
            error: (error) => {
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler(
                    {
                        [EHttpStatus.HTTP_403_FORBIDDEN]: {
                            after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                        },
                    },
                    messageRef
                );

                handle(error);
                return messageRef.message;
            },
            success: () => {
                return t("successes.Webhook URL changed successfully.");
            },
            finally: () => {
                setIsEditing(false);
            },
        });
    };
    const cancelEdit = () => {
        resetCollaborativeURLRef.current?.(urlValue);
        setDraftURL(urlValue);
        setIsEditing(false);
    };

    return (
        <Table.FlexCell
            className={cn(
                "w-[calc(calc(100%_/_6_*_2)_-_theme(spacing.12))] truncate text-center",
                isEditing && "pb-2.5 pt-[calc(theme(spacing.4)_-_2px)]"
            )}
        >
            {!isEditing ? (
                <Flex
                    cursor={canUpdateWebhook ? "pointer" : "default"}
                    justify="center"
                    items="center"
                    gap="1"
                    position="relative"
                    onClick={startEdit}
                >
                    <Box as="span" className="max-w-[calc(100%_-_theme(spacing.6))] truncate">
                        {urlValue}
                    </Box>
                    {canUpdateWebhook && (
                        <Box position="relative">
                            <Box position="absolute" left="2" className="top-1/2 -translate-y-1/2">
                                <IconComponent icon="pencil" size="4" />
                            </Box>
                        </Box>
                    )}
                </Flex>
            ) : (
                <Flex items="center" gap="1">
                    <Collaborative.Input
                        collaborationType={EEditorCollaborationType.AppSettings}
                        uid={webhook.uid}
                        section="webhook"
                        field="url"
                        ref={valueRef}
                        className={cn(
                            "h-6 rounded-none border-x-0 border-t-0 bg-transparent p-0 text-center scrollbar-hide",
                            "focus-visible:border-b-primary focus-visible:ring-0"
                        )}
                        defaultValue={urlValue}
                        onCollaborativeValueResetReady={(resetValue) => {
                            resetCollaborativeURLRef.current = resetValue;
                        }}
                        onValueChange={setDraftURL}
                        onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                        }}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                e.preventDefault();
                                e.stopPropagation();
                                saveEdit();
                                return;
                            }
                        }}
                    />
                    <Button type="button" size="icon-sm" variant="ghost" onClick={saveEdit} title={t("common.Save")}>
                        <IconComponent icon="check" size="4" />
                    </Button>
                    <Button type="button" size="icon-sm" variant="ghost" onClick={cancelEdit} title={t("common.Cancel")}>
                        <IconComponent icon="x" size="4" />
                    </Button>
                </Flex>
            )}
        </Table.FlexCell>
    );
}

export default WebhookURL;
