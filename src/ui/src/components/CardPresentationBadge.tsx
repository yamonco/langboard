import Tooltip from "@/components/base/Tooltip";

/** One accessible renderer for native and extension card presentation. Text only. */
export default function CardPresentationBadge({
    presentationKey,
    axis,
    name,
    description,
    icon,
}: {
    presentationKey: string;
    axis: string;
    name: string;
    description: string;
    icon?: string;
}) {
    return (
        <Tooltip.Root>
            <Tooltip.Trigger asChild>
                <span
                    tabIndex={0}
                    data-card-presentation={presentationKey}
                    data-card-presentation-axis={axis}
                    className={
                        "mb-1 inline-flex max-w-full items-center gap-1 rounded-md border border-primary/30 " +
                        "bg-primary/5 px-1.5 py-0.5 text-xs text-muted-foreground" +
                        " focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    }
                    aria-label={`${name}: ${description}`}
                >
                    {icon && <span aria-hidden="true">{icon}</span>}
                    <span className="truncate">{name}</span>
                </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
                <Tooltip.Content
                    className="max-w-[min(22rem,calc(100vw-2rem))] whitespace-normal break-words"
                    onClick={(event) => event.stopPropagation()}
                >
                    {description}
                </Tooltip.Content>
            </Tooltip.Portal>
        </Tooltip.Root>
    );
}
