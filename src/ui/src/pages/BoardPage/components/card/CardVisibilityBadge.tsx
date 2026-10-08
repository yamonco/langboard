import { Project, ProjectCard } from "@/core/models";
import { useTranslation } from "react-i18next";

export default function CardVisibilityBadge({ card }: { card: ProjectCard.TModel }) {
    const project = Project.Model.useModel(card.project_uid);
    return project ? <ResolvedCardVisibilityBadge card={card} project={project} /> : null;
}

function ResolvedCardVisibilityBadge({ card, project }: { card: ProjectCard.TModel; project: Project.TModel }) {
    const [t] = useTranslation();
    const members = project.useForeignFieldArray("all_members");
    const visibility = card.useField("visibility");
    const hasExternal = members.some((member) => member.isValidUser() && member.membership_classification === "external");
    if (visibility !== "PRIVATE" && !(visibility === "INTERNAL" && hasExternal)) return null;
    const personal = visibility === "PRIVATE";
    return (
        <span
            data-card-visibility={visibility}
            className={
                "mb-1 inline-flex items-center gap-1 rounded-md border border-primary/30 " +
                "bg-primary/5 px-1.5 py-0.5 text-xs text-muted-foreground"
            }
            title={t(personal ? "card.Private visibility guidance" : "card.Whisper visibility guidance")}
        >
            <span aria-hidden="true">{personal ? "🔐" : "🤫"}</span>
            {t(personal ? "card.Private" : "card.Whisper")}
        </span>
    );
}
