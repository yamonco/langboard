import { ProjectCard } from "@/core/models";
import Tooltip from "@/components/base/Tooltip";
import { useTranslation } from "react-i18next";
import useUpdateDateDistance from "@/core/hooks/useUpdateDateDistance";

export default function CardTimestamps({ card, compact = false }: { card: ProjectCard.TModel; compact?: boolean }) {
    const createdAt = card.useField("created_at");
    const updatedAt = card.useField("updated_at");
    const [t] = useTranslation();
    const createdDistance = useUpdateDateDistance(createdAt);
    const updatedDistance = useUpdateDateDistance(updatedAt);
    const exact = (date: Date) => date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "medium" });

    return (
        <span className={`flex min-w-0 flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground ${compact ? "basis-full" : ""}`}>
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <time dateTime={createdAt.toISOString()} tabIndex={0} aria-label={`${t("card.Created")}: ${exact(createdAt)}`}>
                        {t("card.Created")}: {createdDistance}
                    </time>
                </Tooltip.Trigger>
                <Tooltip.Content>{exact(createdAt)}</Tooltip.Content>
            </Tooltip.Root>
            <Tooltip.Root>
                <Tooltip.Trigger asChild>
                    <time dateTime={updatedAt.toISOString()} tabIndex={0} aria-label={`${t("card.Updated")}: ${exact(updatedAt)}`}>
                        {t("card.Updated")}: {updatedDistance}
                    </time>
                </Tooltip.Trigger>
                <Tooltip.Content>{exact(updatedAt)}</Tooltip.Content>
            </Tooltip.Root>
        </span>
    );
}
