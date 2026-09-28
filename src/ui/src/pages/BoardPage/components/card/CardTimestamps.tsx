import { ProjectCard } from "@/core/models";
import Tooltip from "@/components/base/Tooltip";
import { useTranslation } from "react-i18next";

export default function CardTimestamps({ card, compact = false }: { card: ProjectCard.TModel; compact?: boolean }) {
    const createdAt = card.useField("created_at");
    const updatedAt = card.useField("updated_at");
    const [t] = useTranslation();
    const exact = (date: Date) => date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });
    const format = (date: Date) =>
        compact ? date.toLocaleDateString(undefined, { year: "numeric", month: "2-digit", day: "2-digit" }) : exact(date);

    return (
        <span className={`flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground ${compact ? "basis-full" : ""}`}>
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <time dateTime={createdAt.toISOString()} tabIndex={0} aria-label={`${t("card.Created")}: ${exact(createdAt)}`}>
                        {t("card.Created")}: {format(createdAt)}
                    </time>
                </Tooltip.Trigger>
                <Tooltip.Content>{exact(createdAt)}</Tooltip.Content>
            </Tooltip.Root>
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <time dateTime={updatedAt.toISOString()} tabIndex={0} aria-label={`${t("card.Updated")}: ${exact(updatedAt)}`}>
                        {t("card.Updated")}: {format(updatedAt)}
                    </time>
                </Tooltip.Trigger>
                <Tooltip.Content>{exact(updatedAt)}</Tooltip.Content>
            </Tooltip.Root>
        </span>
    );
}
