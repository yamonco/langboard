import { LabelModelBadge } from "./index";
import { ProjectCard } from "@/core/models";

export default function CardCompactLabels({ card }: { card: ProjectCard.TModel }): React.JSX.Element | null {
    const labels = card.useForeignFieldArray("labels");
    if (!labels.length) return null;
    return (
        <span className="inline-flex shrink-0 flex-wrap items-center gap-1">
            {labels.map((label) => (
                <LabelModelBadge key={label.uid} model={label} compact />
            ))}
        </span>
    );
}
