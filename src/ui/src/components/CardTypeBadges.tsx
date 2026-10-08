import useHasExternalProjectMember from "@/core/cards/useHasExternalProjectMember";
import { MetadataModel, Project, ProjectCard } from "@/core/models";
import { useTranslation } from "react-i18next";
import {
    CARD_PRESENTATION_KEY,
    CARD_VISIBILITY_PRESENTATIONS,
    cardPresentationText,
    cardVisibilityPresentation,
    parseCardPresentation,
} from "@/core/cards/CardPresentation";
import CardPresentationBadge from "@/components/CardPresentationBadge";

export default function CardTypeBadges({ card }: { card: ProjectCard.TModel }) {
    const project = Project.Model.useModel(card.project_uid);
    return (
        <>
            {project && <ResolvedCardTypeBadges card={card} project={project} />}
            <ExtensionCardBadge cardUID={card.uid} />
        </>
    );
}

function ResolvedCardTypeBadges({ card, project }: { card: ProjectCard.TModel; project: Project.TModel }) {
    const [t] = useTranslation();
    const visibility = card.useField("visibility");
    const hasExternal = useHasExternalProjectMember(project);
    const presentation = cardVisibilityPresentation(visibility, hasExternal);
    if (!presentation) return null;
    const definition = CARD_VISIBILITY_PRESENTATIONS[presentation];
    return (
        <span data-card-visibility={visibility}>
            <CardPresentationBadge
                presentationKey={definition.key}
                axis="visibility"
                icon={definition.icon}
                name={t(definition.nameKey)}
                description={t(definition.descriptionKey)}
            />
        </span>
    );
}

function ExtensionCardBadge({ cardUID }: { cardUID: string }) {
    const metadata = MetadataModel.Model.useModel(cardUID, [cardUID]);
    return metadata?.type === "card" ? <ResolvedExtensionBadge metadata={metadata} /> : null;
}

function ResolvedExtensionBadge({ metadata }: { metadata: MetadataModel.TModel }) {
    const values = metadata.useField("metadata");
    const [, i18n] = useTranslation();
    const item = parseCardPresentation(values?.[CARD_PRESENTATION_KEY]);
    if (!item) return null;
    const text = cardPresentationText(item, i18n.language);
    return <CardPresentationBadge presentationKey={item.key} axis={item.axis} icon={item.icon} {...text} />;
}
