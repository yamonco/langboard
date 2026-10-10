import Avatar from "@/components/base/Avatar";
import Box from "@/components/base/Box";
import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import PillList from "@/components/base/PillList";
import Popover from "@/components/base/Popover";
import SubmitButton from "@/components/base/SubmitButton";
import Toast from "@/components/base/Toast";
import useCopyInternalBot from "@/controllers/api/settings/internalBots/useCopyInternalBot";
import useDeleteInternalBot from "@/controllers/api/settings/internalBots/useDeleteInternalBot";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import { InternalBotModel } from "@/core/models";
import { SettingRole } from "@/core/models/roles";
import { ROUTES } from "@/core/routing/constants";
import { EHttpStatus } from "@langboard/core/enums";
import { memo, useState } from "react";
import { useTranslation } from "react-i18next";

export interface IInternalBotProps {
    internalBot: InternalBotModel.TModel;
}

const InternalBot = memo(({ internalBot }: IInternalBotProps) => {
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { currentUser } = useAppSetting();
    const settingRoleActions = currentUser.useField("setting_role_actions");
    const { hasRoleAction } = useRoleActionFilter(settingRoleActions);
    const canCopyInternalBot = hasRoleAction(SettingRole.EAction.InternalBotCreate);
    const canDeleteInternalBot = hasRoleAction(SettingRole.EAction.InternalBotDelete);
    const { isValidating, setIsValidating } = useAppSetting();
    const { mutateAsync: copyInternalBotMutateAsync } = useCopyInternalBot(internalBot, { interceptToast: true });
    const { mutateAsync: deleteInternalBotMutateAsync } = useDeleteInternalBot(internalBot, { interceptToast: true });
    const [isOpened, setIsOpened] = useState(false);
    const displayName = internalBot.useField("display_name");
    const botType = internalBot.useField("bot_type");
    const avatar = internalBot.useField("avatar");
    const isDefault = internalBot.useField("is_default");

    const copyInternalBot = (e: React.MouseEvent<HTMLButtonElement> | React.PointerEvent<HTMLButtonElement>) => {
        e.preventDefault();
        e.stopPropagation();

        if (isValidating || !canCopyInternalBot) {
            return;
        }

        setIsValidating(true);

        const promise = copyInternalBotMutateAsync({});

        Toast.Add.promise(promise, {
            loading: t("common.Creating..."),
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
                return t("successes.Internal bot copied successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    const deleteInternalBot = (e: React.MouseEvent<HTMLButtonElement>) => {
        e.preventDefault();
        e.stopPropagation();

        if (isValidating || !canDeleteInternalBot) {
            return;
        }

        setIsValidating(true);

        const promise = deleteInternalBotMutateAsync({});

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
                return t("successes.Internal bot deleted successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    const toInternalBotDetails = () => {
        navigate(ROUTES.SETTINGS.INTERNAL_BOT_DETAILS(internalBot.uid), { smooth: true });
    };

    const changeOpenState = (opened: bool) => {
        if (isValidating) {
            return;
        }

        setIsOpened(opened);
    };

    return (
        <PillList.ItemRoot size="sm" className="cursor-pointer" onClick={toInternalBotDetails}>
            <PillList.ItemTitle>
                <Avatar.Root>
                    <Avatar.Image src={avatar} />
                    <Avatar.Fallback>
                        <IconComponent icon="bot" className="size-2/3" />
                    </Avatar.Fallback>
                </Avatar.Root>
                <Box w="full">
                    <Box>{displayName}</Box>
                    <Box w="full" textSize="xs" className="text-muted-foreground/70">
                        {t(`internalBot.botTypes.${botType}`)}
                    </Box>
                </Box>
            </PillList.ItemTitle>
            <PillList.ItemContent
                onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                }}
            >
                <Flex items="center" justify="end" gap="1">
                    {canCopyInternalBot ? (
                        <Button
                            variant="outline"
                            size="icon-sm"
                            title={t("common.Copy")}
                            aria-label={t("common.Copy")}
                            titleSide="bottom"
                            disabled={isValidating}
                            onClick={copyInternalBot}
                        >
                            <IconComponent icon="copy" size="4" />
                        </Button>
                    ) : null}
                    {isDefault ? (
                        <span className="whitespace-nowrap text-secondary-foreground/50">{` (${t("common.default")})`}</span>
                    ) : canDeleteInternalBot ? (
                        <Popover.Root open={isOpened} onOpenChange={changeOpenState}>
                            <Popover.Trigger asChild>
                                <Button variant="destructive" size="icon-sm" title={t("common.Delete")} aria-label={t("common.Delete")} titleSide="bottom" disabled={isValidating}>
                                    <IconComponent icon="trash-2" size="5" />
                                </Button>
                            </Popover.Trigger>
                            <Popover.Content align="end">
                                <Box mb="1" textSize={{ initial: "sm", sm: "base" }} weight="semibold" className="text-center">
                                    {t("ask.Are you sure you want to delete this internal bot?")}
                                </Box>
                                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                                    {t("common.deleteDescriptions.All data will be lost.")}
                                </Box>
                                <Box maxW="full" textSize="sm" weight="bold" className="text-center text-red-500">
                                    {t("common.deleteDescriptions.This action cannot be undone.")}
                                </Box>
                                <Flex items="center" justify="end" gap="1" mt="2">
                                    <Button type="button" variant="secondary" size="sm" disabled={isValidating} onClick={() => setIsOpened(false)}>
                                        {t("common.Cancel")}
                                    </Button>
                                    <SubmitButton
                                        type="button"
                                        variant="destructive"
                                        size="sm"
                                        onClick={deleteInternalBot}
                                        isValidating={isValidating}
                                    >
                                        {t("common.Delete")}
                                    </SubmitButton>
                                </Flex>
                            </Popover.Content>
                        </Popover.Root>
                    ) : null}
                </Flex>
            </PillList.ItemContent>
        </PillList.ItemRoot>
    );
});

export default InternalBot;
