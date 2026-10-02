import { createRoot } from "react-dom/client";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import "@/core/injection/StringExtensions";
import useUpdateDateDistance from "@/core/hooks/useUpdateDateDistance";
import { formatDateTime } from "./LocaleFormat";
import { SUPPORTED_LOCALES } from "./LocalePolicy";

const date = new Date(Date.now() - 300000);
function Fixture() {
    const [, language] = useTranslation();
    const distance = useUpdateDateDistance(date);
    return (
        <>
            <output data-testid="relative">{distance}</output>
            <output data-testid="exact">{formatDateTime(date, language.language)}</output>
            {SUPPORTED_LOCALES.map((locale) => (
                <button key={locale} onClick={() => void language.changeLanguage(locale)}>
                    {locale}
                </button>
            ))}
        </>
    );
}
function render() {
    createRoot(document.getElementById("root")!).render(<Fixture />);
}
if (i18n.isInitialized) render();
else i18n.on("initialized", render);
