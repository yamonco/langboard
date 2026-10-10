import { useTranslation } from "react-i18next";
import Flex from "@/components/base/Flex";
import { useAccountSetting } from "@/core/providers/AccountSettingProvider";
import UserPreferenceLanguageSwitcher from "@/components/LanguageSwitcher/UserPreference";

function PreferenceLanguage() {
    const { currentUser } = useAccountSetting();
    const [t] = useTranslation();

    return (
        <Flex items="center" pb="3" gap="3" className="flex-wrap">
            <div className="min-w-0 flex-1">
                <h4 className="text-lg font-semibold tracking-tight">{t("myAccount.Default language")}</h4>
                <p className="text-sm text-muted-foreground">{t("myAccount.Default language description")}</p>
            </div>
            <UserPreferenceLanguageSwitcher currentUser={currentUser} variant="outline" triggerType="text" />
        </Flex>
    );
}

export default PreferenceLanguage;
