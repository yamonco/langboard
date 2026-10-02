import { LANGUAGE_LOCALES } from "@/constants";
import { useTranslation } from "react-i18next";
import Button, { type ButtonProps } from "@/components/base/Button";
import DropdownMenu from "@/components/base/DropdownMenu";
import IconComponent from "@/components/base/IconComponent";
import { cn } from "@/core/utils/ComponentUtils";
import { useMemo } from "react";

export interface ILanguageSwitcherProps {
    variant?: ButtonProps["variant"];
    triggerType?: "icon" | "text";
    buttonClassNames?: string;
    hideTriggerIcon?: bool;
    size?: ButtonProps["size"];
    asForm?: {
        initialValue: string;
        disabled?: bool;
        onChange: (lang: string) => void;
    };
}

function LanguageSwitcher({
    variant,
    triggerType,
    buttonClassNames,
    hideTriggerIcon,
    size = "default",
    asForm,
}: ILanguageSwitcherProps): React.JSX.Element {
    const [t, i18n] = useTranslation();
    const curLang = useMemo(() => (asForm ? asForm.initialValue : i18n.language), [asForm, asForm?.initialValue, i18n, i18n.language]);

    const changeLanguageHandler = (lang: string) => {
        if (asForm) {
            asForm.onChange(lang);
            return;
        }

        if (!LANGUAGE_LOCALES.includes(lang)) {
            return;
        }

        i18n.changeLanguage(lang);
    };

    const langs = LANGUAGE_LOCALES.filter((locale) => locale !== curLang);

    return (
        <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
                <Button
                    variant={variant ?? "default"}
                    className={cn("inline-flex", buttonClassNames)}
                    title={t("locales.title")}
                    size={size}
                    disabled={asForm?.disabled}
                >
                    {triggerType === "text" ? t(`locales.${curLang}`) : <IconComponent icon={`country-${curLang.split("-").pop()}`} />}
                    {hideTriggerIcon ? null : <IconComponent icon="chevron-down" size="4" className="ml-3" />}
                </Button>
            </DropdownMenu.Trigger>

            {langs.length === 0 ? null : (
                <DropdownMenu.Content>
                    {langs.map((locale) => {
                        return (
                            <DropdownMenu.Item onClick={() => changeLanguageHandler(locale)} key={locale}>
                                <IconComponent icon={`country-${locale.split("-").pop()}`} className="mr-2" />
                                {t(`locales.${locale}`)}
                            </DropdownMenu.Item>
                        );
                    })}
                </DropdownMenu.Content>
            )}
        </DropdownMenu.Root>
    );
}

export default LanguageSwitcher;
