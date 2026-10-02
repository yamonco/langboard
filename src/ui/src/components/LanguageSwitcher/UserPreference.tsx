import { useTranslation } from "react-i18next";
import Toast from "@/components/base/Toast";
import useUpdatePreferredLanguage from "@/controllers/api/account/useUpdatePreferredLanguage";
import LanguageSwitcher from "@/components/LanguageSwitcher";
import setupApiErrorHandler from "@/core/helpers/setupApiErrorHandler";
import { AuthUser } from "@/core/models";
import { useState } from "react";
import { normalizeLocale } from "@/core/utils/LocalePolicy";

export interface IUserPreferenceLanguageSwitcherProps extends Omit<React.ComponentProps<typeof LanguageSwitcher>, "asForm"> {
    currentUser: AuthUser.TModel;
}

function UserPreferenceLanguageSwitcher({ currentUser, ...props }: IUserPreferenceLanguageSwitcherProps): React.JSX.Element {
    const [isValidating, setIsValidating] = useState(false);
    const [t, i18n] = useTranslation();
    const { mutateAsync } = useUpdatePreferredLanguage({ interceptToast: true });
    const preferredLang = currentUser.useField("preferred_lang");

    const handleUpdate = (lang: string) => {
        if (isValidating || lang === preferredLang) {
            return;
        }

        const previousLanguage = normalizeLocale(i18n.language);
        setIsValidating(true);

        const promise = i18n.changeLanguage(lang).then(() => mutateAsync({ lang }));

        Toast.Add.promise(promise, {
            loading: t("common.Updating..."),
            error: (error) => {
                i18n.changeLanguage(previousLanguage);
                const messageRef = { message: "" };
                const { handle } = setupApiErrorHandler({}, messageRef);

                handle(error);
                return messageRef.message;
            },
            success: () => {
                currentUser.preferred_lang = lang;
                return t("successes.Preferred language updated successfully.");
            },
            finally: () => {
                setIsValidating(false);
            },
        });
    };

    return (
        <LanguageSwitcher
            {...props}
            asForm={{
                initialValue: normalizeLocale(i18n.language),
                disabled: isValidating,
                onChange: handleUpdate,
            }}
        />
    );
}

export default UserPreferenceLanguageSwitcher;
