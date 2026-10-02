import Breadcrumb from "@/components/base/Breadcrumb";
import Dialog from "@/components/base/Dialog";
import MarkdownThinkBlock from "@/components/Markdown/ThinkBlock";
import Calendar from "@/components/base/Calendar";
import { createRoot } from "react-dom/client";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";
import "@/core/injection/StringExtensions";
import useUpdateDateDistance from "@/core/hooks/useUpdateDateDistance";
import { formatDateTime, formatTimerDuration, formatNumber } from "./LocaleFormat";
import { SUPPORTED_LOCALES } from "./LocalePolicy";

const date = new Date(Date.now() - 300000);
function Fixture() {
    const [t, language] = useTranslation();
    const distance = useUpdateDateDistance(date);
    return (
        <>
            <div data-testid="common-ui">
                <Breadcrumb.Root>
                    <Breadcrumb.List>
                        <Breadcrumb.Item>
                            <Breadcrumb.Ellipsis />
                        </Breadcrumb.Item>
                    </Breadcrumb.List>
                </Breadcrumb.Root>
                <Dialog.Root>
                    <Dialog.CloseButton />
                </Dialog.Root>
                <MarkdownThinkBlock>Fixture content</MarkdownThinkBlock>
            </div>
            <output data-testid="relative">{distance}</output>
            <output data-testid="overdue-one">{t("card.Overdue by {{count}} day", { count: 1 })}</output>
            <output data-testid="overdue-other">{t("card.Overdue by {{count}} day", { count: 2 })}</output>
            <output data-testid="duration">{formatTimerDuration({ hours: 1, minutes: 2, seconds: 3 }, language.language)}</output>
            <output data-testid="count">{formatNumber(12345, language.language)}</output>
            <div data-testid="calendar">
                <Calendar value={new Date(2026, 9, 3, 13)} onChange={() => {}} hideTime />
            </div>
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
