import { normalizeLocale } from "@/core/utils/LocalePolicy";
import { useTranslation } from "react-i18next";

const MarkdownDateBlock = ({ children = [] }: { children?: string[] }) => {
    const [t, i18n] = useTranslation();
    if (children.length === 0) {
        return <span className="w-fit rounded-sm border border-border bg-muted px-1 text-foreground">{t("date.Invalid date")}</span>;
    }

    const dateString = children[0];
    const date = new Date(dateString);

    if (Number.isNaN(date.getTime())) return <span>{t("date.Invalid date")}</span>;

    const options: Intl.DateTimeFormatOptions = { year: "numeric", month: "long", day: "numeric" };
    const formattedDate = date.toLocaleDateString(normalizeLocale(i18n.language), options);

    return <span className="w-fit rounded-sm border border-border bg-muted px-1 text-foreground">{formattedDate}</span>;
};

export default MarkdownDateBlock;
