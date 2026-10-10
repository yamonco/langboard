import { memo } from "react";
import { useTranslation } from "react-i18next";
import UserAvatar from "@/components/UserAvatar";
import { ROUTES } from "@/core/routing/constants";
import { AuthUser } from "@/core/models";
import { useAuth } from "@/core/providers/AuthProvider";
import { usePageNavigateRef } from "@/core/hooks/usePageNavigate";
import UserPreferenceLanguageSwitcher from "@/components/LanguageSwitcher/UserPreference";

interface IHeaderUserMenuProps {
    currentUser: AuthUser.TModel;
}

const HeaderUserMenu = memo(({ currentUser }: IHeaderUserMenuProps) => {
    const { signOut } = useAuth();
    const navigate = usePageNavigateRef();
    const [t] = useTranslation();

    return (
        <UserAvatar.Root
            userOrBot={currentUser}
            listAlign="end"
            avatarSize={{
                initial: "sm",
                md: "default",
            }}
            className="mx-1"
        >
            <UserAvatar.List>
                <UserAvatar.ListItem className="cursor-pointer" onClick={() => navigate(ROUTES.ACCOUNT.PROFILE, { smooth: true })}>
                    {t("myAccount.My account")}
                </UserAvatar.ListItem>
                <UserAvatar.ListSeparator />
                <UserAvatar.ListItem className="cursor-default gap-3 hover:bg-transparent hover:text-inherit">
                    <span className="flex-1">{t("myAccount.Language")}</span>
                    <UserPreferenceLanguageSwitcher currentUser={currentUser} variant="outline" triggerType="text" size="sm" />
                </UserAvatar.ListItem>
                <UserAvatar.ListSeparator />
                <UserAvatar.ListItem className="cursor-pointer" onClick={() => navigate(ROUTES.SETTINGS.ROUTE, { smooth: true })}>
                    {t("settings.App settings")}
                </UserAvatar.ListItem>
                <UserAvatar.ListSeparator />
                <UserAvatar.ListItem
                    className="cursor-pointer"
                    onClick={async () => {
                        await signOut();
                    }}
                >
                    {t("myAccount.Sign out")}
                </UserAvatar.ListItem>
                <UserAvatar.ListSeparator />
            </UserAvatar.List>
        </UserAvatar.Root>
    );
});

export default HeaderUserMenu;
