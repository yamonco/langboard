import Button from "@/components/base/Button";
import Flex from "@/components/base/Flex";
import IconComponent from "@/components/base/IconComponent";
import Toast from "@/components/base/Toast";
import useDeleteSelectedUsersInSettings from "@/controllers/api/settings/users/useDeleteSelectedUsersInSettings";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import useRoleActionFilter from "@/core/hooks/useRoleActionFilter";
import { SettingRole } from "@/core/models/roles";
import { useAppSetting } from "@/core/providers/AppSettingProvider";
import { usePageHeader } from "@/core/providers/PageHeaderProvider";
import { ROUTES } from "@/core/routing/constants";
import EmployeeMembershipSettings from "@/pages/SettingsPage/components/users/EmployeeMembershipSettings";
import UserList from "@/pages/SettingsPage/components/users/UserList";
import { EHttpStatus } from "@langboard/core/enums";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

function UsersPage() {
    const { setPageAliasRef } = usePageHeader();
    const [t] = useTranslation();
    const navigate = usePageNavigateRef();
    const { currentUser, isValidating, setIsValidating } = useAppSetting();
    const [selectedUsers, setSelectedUsers] = useState<string[]>([]);
    const { mutate: deleteSelectedUsersMutate } = useDeleteSelectedUsersInSettings();
    const settingRoleActions = currentUser.useField("setting_role_actions");
    const { hasRoleAction } = useRoleActionFilter(settingRoleActions);
    const canDeleteUser = hasRoleAction(SettingRole.EAction.UserDelete);

    useEffect(() => {
        setPageAliasRef.current("Users");
    }, []);

    const openCreateDialog = () => {
        navigate(ROUTES.SETTINGS.CREATE_USER);
    };

    const deleteSelectedUsers = () => {
        if (isValidating || !selectedUsers.length || !canDeleteUser) {
            return;
        }

        setIsValidating(true);

        deleteSelectedUsersMutate(
            {
                user_uids: selectedUsers,
            },
            {
                onSuccess: () => {
                    Toast.Add.success(t("successes.Selected webhooks deleted successfully."));
                    setSelectedUsers([]);
                },
                onError: (error) => {
                    const { handle } = setupApiErrorHandler({
                        [EHttpStatus.HTTP_403_FORBIDDEN]: {
                            after: () => navigate(ROUTES.ERROR(EHttpStatus.HTTP_403_FORBIDDEN), { replace: true }),
                        },
                    });

                    handle(error);
                },
                onSettled: () => {
                    setIsValidating(false);
                },
            }
        );
    };

    return (
        <>
            <Flex
                justify={{ sm: "between" }}
                direction={{ initial: "col", sm: "row" }}
                gap="2"
                mb="4"
                pb="2"
                textSize="3xl"
                weight="semibold"
                className="scroll-m-20 tracking-tight"
            >
                <span className="w-36">{t("settings.Users")}</span>
                <Flex gap="2" wrap justify="end" maxW={{ initial: "full", sm: "auto" }}>
                    {selectedUsers.length > 0 && canDeleteUser && (
                        <Button variant="destructive" disabled={isValidating} className="gap-2 pl-2 pr-3" onClick={deleteSelectedUsers}>
                            <IconComponent icon="trash" size="4" />
                            {t("common.Delete")}
                        </Button>
                    )}
                    {hasRoleAction(SettingRole.EAction.UserCreate) && (
                        <Button variant="outline" disabled={isValidating} className="gap-2 pl-2 pr-3" onClick={openCreateDialog}>
                            <IconComponent icon="plus" size="4" />
                            {t("settings.Add new")}
                        </Button>
                    )}
                </Flex>
            </Flex>
            <EmployeeMembershipSettings />
            <UserList selectedUsers={selectedUsers} setSelectedUsers={setSelectedUsers} />
        </>
    );
}

export default UsersPage;
